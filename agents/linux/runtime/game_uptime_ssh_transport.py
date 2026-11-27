#!/usr/bin/env python3
"""Explicit #928 SSH transport for the existing retained Agent sessions.

No key enrollment, sshd modification, installation, journal cleanup or live
update authorization. Both endpoint inventory and host identity are pinned
outside the replaceable DSM tree by an independent root operator. The remote
command must be the audited root-owned snapshot, not /opt/capivara-agent.
"""
from __future__ import annotations

import base64
import contextlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

TRUST_DIR = Path("/etc/capivara-dsm")
ENDPOINTS = TRUST_DIR / "agent-session-endpoints.json"
IDENTITY_KEY = TRUST_DIR / "agent-session-ssh-key"
LOCAL_ID = TRUST_DIR / "agent-session-id"
LIBEXEC = Path("/usr/local/libexec/capivara-dsm-928-agent")
REMOTE_SCRIPT = LIBEXEC / "game_uptime_ssh_transport.py"
REMOTE_COMMAND = ("/usr/bin/python3 -I -S " + str(REMOTE_SCRIPT) + " --serve")
MODULES = (
    "game_uptime_ssh_transport.py", "game_uptime_hold_coordinator.py",
    "game_uptime_maintenance_hold.py", "game_uptime_transaction_binding.py",
    "game_uptime_privileged_flock.py", "game_uptime_finalization_flock.py",
    "game_uptime_privileged_journal_witness.py",
    "game_uptime_wire_replay_service.py", "game_uptime_durable_wire_replay.py",
)
_ID = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z")


class SSHTransportBlocked(RuntimeError):
    pass


def _root_directory(path):
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SSHTransportBlocked("untrusted_ssh_directory")


def _root_file(path, maximum, *, private=True):
    path = Path(path)
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
            or before.st_nlink != 1 or before.st_mode & 0o022
            or (private and stat.S_IMODE(before.st_mode) != 0o600)
            or not 0 < before.st_size <= maximum):
        raise SSHTransportBlocked("untrusted_ssh_file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        def identity(meta):
            return (meta.st_dev, meta.st_ino, meta.st_uid, meta.st_mode,
                    meta.st_nlink, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)
        if identity(os.fstat(fd)) != identity(before):
            raise SSHTransportBlocked("ssh_file_changed")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(maximum + 1)
        if (len(raw) != before.st_size or identity(os.fstat(fd)) != identity(before)
                or identity(path.lstat()) != identity(before)):
            raise SSHTransportBlocked("ssh_file_changed")
        return raw
    finally:
        os.close(fd)


def _snapshot_trusted():
    if os.geteuid() != 0 or Path(__file__) != REMOTE_SCRIPT:
        raise SSHTransportBlocked("audited_root_snapshot_required")
    for directory in (Path("/usr"), Path("/usr/local"), Path("/usr/local/libexec"), LIBEXEC):
        _root_directory(directory)
    for module in MODULES:
        _root_file(LIBEXEC / module, 1024 * 1024, private=False)


def _endpoint_inventory(raw: bytes, expected_agent_ids: list[str]) -> dict:
    """Strict operator inventory, with a distinct pinned Ed25519 host key per Agent."""
    if (type(expected_agent_ids) is not list or not 1 <= len(expected_agent_ids) <= 64
            or any(type(x) is not str or not _ID.fullmatch(x) for x in expected_agent_ids)
            or len(set(expected_agent_ids)) != len(expected_agent_ids)):
        raise SSHTransportBlocked("invalid_ssh_expected_inventory")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SSHTransportBlocked("duplicate_ssh_inventory_key")
            result[key] = value
        return result
    try:
        document = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(document, dict) or set(document) != set(expected_agent_ids)):
            raise SSHTransportBlocked("ssh_inventory_incomplete")
        result, seen = {}, set()
        for agent, entry in document.items():
            if (not isinstance(entry, dict) or set(entry) != {"host", "port", "host_key"}
                    or type(entry["host"]) is not str or type(entry["port"]) is not int
                    or not 1 <= entry["port"] <= 65535 or type(entry["host_key"]) is not str):
                raise SSHTransportBlocked("invalid_ssh_endpoint")
            host = entry["host"]
            if not _HOST.fullmatch(host):
                if "%" in host or not isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address):
                    raise SSHTransportBlocked("invalid_ssh_host")
            algorithm, key = entry["host_key"].split(" ")
            blob = base64.b64decode(key, validate=True)
            if (algorithm != "ssh-ed25519" or len(blob) != 51
                    or blob[:19] != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20"
                    or base64.b64encode(blob).decode("ascii") != key
                    or blob in seen):
                raise SSHTransportBlocked("invalid_or_duplicate_ssh_host_key")
            seen.add(blob)
            result[agent] = dict(entry)
        return result
    except (ValueError, TypeError, UnicodeError) as exc:
        raise SSHTransportBlocked("invalid_ssh_inventory") from exc


def _ssh_argv(agent, endpoint, known_hosts, identity):
    """No user config, agent forwarding, password fallback or host-key discovery."""
    options = {
        "BatchMode": "yes", "IdentitiesOnly": "yes", "IdentityAgent": "none",
        "StrictHostKeyChecking": "yes", "GlobalKnownHostsFile": "/dev/null",
        "UserKnownHostsFile": str(known_hosts), "HostKeyAlias": "dsm928-" + agent,
        "HostKeyAlgorithms": "ssh-ed25519", "UpdateHostKeys": "no",
        "VerifyHostKeyDNS": "no", "CheckHostIP": "no",
        "PasswordAuthentication": "no", "KbdInteractiveAuthentication": "no",
        "PreferredAuthentications": "publickey", "PubkeyAuthentication": "yes",
        "GSSAPIAuthentication": "no", "HostbasedAuthentication": "no",
        "ForwardAgent": "no", "ForwardX11": "no", "ClearAllForwardings": "yes",
        "ControlMaster": "no", "ControlPath": "none", "ProxyCommand": "none",
        "ProxyJump": "none", "PermitLocalCommand": "no", "RequestTTY": "no",
        "ConnectTimeout": "8", "ConnectionAttempts": "1",
        "ServerAliveInterval": "5", "ServerAliveCountMax": "2",
        "EscapeChar": "none",
    }
    argv = ["/usr/bin/ssh", "-F", "/dev/null", "-T", "-i", str(identity)]
    for name, value in options.items():
        argv.extend(("-o", name + "=" + value))
    argv.extend(("-p", str(endpoint["port"]), "-l", "root", "--",
                 endpoint["host"], REMOTE_COMMAND))
    return argv


@contextlib.contextmanager
def _open_ssh_session(agent, endpoint, known_hosts, identity):
    from game_uptime_hold_coordinator import _session_read, _session_bytes
    proc = subprocess.Popen(
        _ssh_argv(agent, endpoint, known_hosts, identity),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        bufsize=0, close_fds=True, start_new_session=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/root", "LANG": "C"})
    try:
        # SSH completes host and client authentication before the audited
        # remote command can reply. Verify its independently pinned Agent ID
        # before allowing any PREPARE message to leave the Controller.
        hello = _session_read(proc.stdout.fileno(), time.monotonic() + 10)
        if _session_bytes(hello) != _session_bytes({
                "protocol": "dsm928-ssh-agent-session-v1",
                "status": "authenticated_endpoint_ready", "agent_id": agent,
                "live_no_drain_authorized": False}):
            raise SSHTransportBlocked("ssh_agent_identity_mismatch")
        os.set_blocking(proc.stdin.fileno(), False)
        yield (proc.stdout.fileno(), proc.stdin.fileno())
    finally:
        if proc.stdin:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


@contextlib.contextmanager
def _pinned_ssh_openers(expected_agent_ids):
    """Shared trust validation for probe and retained transaction sessions."""
    if os.geteuid() != 0:
        raise SSHTransportBlocked("root_ssh_coordinator_required")
    for folder in (Path("/etc"), TRUST_DIR):
        _root_directory(folder)
    endpoints = _endpoint_inventory(
        _root_file(ENDPOINTS, 65536), expected_agent_ids)
    # Never log or export the dedicated private key.
    _root_file(IDENTITY_KEY, 16384)
    with tempfile.TemporaryDirectory(prefix="dsm928-ssh-host-pins-") as tmp:
        known = Path(tmp) / "known_hosts"
        known.write_text("".join("dsm928-" + agent + " " + entry["host_key"] + "\n"
                                 for agent, entry in sorted(endpoints.items())),
                         encoding="ascii")
        known.chmod(0o600)
        openers = {agent: (lambda a=agent, e=entry:
                           _open_ssh_session(a, e, known, IDENTITY_KEY))
                   for agent, entry in endpoints.items()}
        yield openers


@contextlib.contextmanager
def retain_ssh_agent_sessions(*, transaction_id, release_sha256, issued_at,
                              expires_at, expected_agent_ids,
                              local_hybrid_agent_id=None,
                              recover_existing=False, operator_reviewed=False):
    """Root-only transport adapter; preserve full scope on every remote host.

    A Hybrid partition is admitted only against the independently pinned
    local identity, not inferred from missing SSH endpoints. The caller
    must still establish the actual retained local scope.
    """
    _snapshot_trusted()
    if str(LIBEXEC) not in sys.path:
        raise SSHTransportBlocked("audited_snapshot_import_path_required")
    from game_uptime_hold_coordinator import retain_distributed_agent_sessions
    if local_hybrid_agent_id is not None:
        for directory in (Path("/etc"), TRUST_DIR):
            _root_directory(directory)
        raw = _root_file(LOCAL_ID, 192)
        if (type(local_hybrid_agent_id) is not str
                or not _ID.fullmatch(local_hybrid_agent_id)
                or raw != (local_hybrid_agent_id + "\n").encode("ascii")
                or type(expected_agent_ids) is not list
                or local_hybrid_agent_id not in expected_agent_ids):
            raise SSHTransportBlocked("pinned_local_hybrid_identity_mismatch")
    if (type(expected_agent_ids) is not list
            or len(set(expected_agent_ids)) != len(expected_agent_ids)):
        raise SSHTransportBlocked("invalid_ssh_expected_inventory")
    standalone_ids = [agent for agent in expected_agent_ids if agent != local_hybrid_agent_id]
    with _pinned_ssh_openers(standalone_ids) as openers:
        with retain_distributed_agent_sessions(
                transaction_id=transaction_id, release_sha256=release_sha256,
                issued_at=issued_at, expires_at=expires_at,
                expected_agent_ids=expected_agent_ids,
                local_hybrid_agent_id=local_hybrid_agent_id,
                session_openers=openers, recover_existing=recover_existing,
                operator_reviewed=operator_reviewed) as receipt:
            yield {**receipt, "ssh_host_keys_authenticated": True,
                   "ssh_remote_agent_id_matched": True,
                   "remote_agents_acked": False,
                   "live_no_drain_authorized": False}


def probe_ssh_agent_sessions(expected_agent_ids):
    """Read-only operational preflight, one authenticated probe per pinned host.

    A failure is reported against its pinned identity, never treated as an
    offline exemption. No remote maintenance journal or lock is created.
    """
    from game_uptime_hold_coordinator import probe_agent_session
    results = {}
    with _pinned_ssh_openers(expected_agent_ids) as openers:
        for agent, opener in sorted(openers.items()):
            try:
                with opener() as (read_fd, write_fd):
                    probe_agent_session(read_fd, write_fd, agent_id=agent)
                results[agent] = "authenticated_protocol_verified"
            except (OSError, RuntimeError, ValueError):
                results[agent] = "blocked_or_unreachable"
    complete = all(value == "authenticated_protocol_verified"
                   for value in results.values())
    return {"kind": "DSM928SSHOperationalProbe", "schema_version": 1,
            "status": "all_endpoints_authenticated" if complete else "blocked",
            "agent_results": results, "maintenance_state_changed": False,
            "remote_agents_acked": False, "live_no_drain_authorized": False}


def _serve():
    _snapshot_trusted()
    for directory in (Path("/etc"), TRUST_DIR):
        _root_directory(directory)
    raw = _root_file(LOCAL_ID, 192)
    agent = raw.decode("ascii").removesuffix("\n")
    if not _ID.fullmatch(agent) or raw != (agent + "\n").encode("ascii"):
        raise SSHTransportBlocked("invalid_pinned_agent_identity")
    # Isolated Python only imports from the verified root-owned snapshot.
    sys.path.insert(0, str(LIBEXEC))
    from game_uptime_hold_coordinator import serve_prepared_agent_session, _session_write
    _session_write(1, {"protocol": "dsm928-ssh-agent-session-v1",
                       "status": "authenticated_endpoint_ready", "agent_id": agent,
                       "live_no_drain_authorized": False}, time.monotonic() + 10)
    serve_prepared_agent_session(0, 1, local_agent_id=agent)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--serve"]:
            _serve()
        elif len(sys.argv) >= 3 and sys.argv[1] == "--probe":
            _snapshot_trusted()
            sys.path.insert(0, str(LIBEXEC))
            report = probe_ssh_agent_sessions(sys.argv[2:])
            print(json.dumps(report, sort_keys=True))
            raise SystemExit(0 if report["status"] == "all_endpoints_authenticated" else 2)
        else:
            raise SystemExit(2)
    except (OSError, RuntimeError, ValueError):
        # No credentials, endpoints, key material or remote data in logs.
        raise SystemExit(2)
