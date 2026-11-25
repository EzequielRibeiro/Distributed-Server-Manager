#!/usr/bin/env python3
"""Root-only, fail-closed preparation of DSM #928 maintenance evidence.

Not connected to update.sh, Controller dispatch, Agent startup or systemd.
This is a *preparatory* transaction owner, never an approval to update live
games. An existing or partially written persistent journal MUST remain a
blocker after a crash, including if the /run marker is lost on reboot.

Terminal decisions can be recorded durably under retained locks. Recording
is not finalization or permission to clear pending evidence; no automatic
release, renewal or removal is exposed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time
import secrets
import select
import hashlib
import subprocess
from contextlib import contextmanager, ExitStack
from typing import Iterator

from game_uptime_maintenance_hold import HOLD_PATH, PENDING_PATH
from game_uptime_transaction_binding import BINDING_PATH

_ID = re.compile(r"[0-9a-f]{32}\Z")
_AGENT_ID = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")


class HoldPreparationBlocked(RuntimeError):
    """Operator recovery is required; never retry by deleting evidence."""


def _trusted_directory(path: Path, uid: int, *,
                       runtime_readable: bool = False) -> None:
    """Refuse writable, symlinked or foreign storage, including its parent.

    An Agent/Worker may use a distinct UID and GID. The *ephemeral hold*
    directory and its ancestors must therefore be traversable by others;
    this never applies to the private persistent journal directory.
    """
    for candidate in (path.parent, path):
        info = candidate.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or (runtime_readable and not info.st_mode & stat.S_IXOTH)):
            raise HoldPreparationBlocked("untrusted_maintenance_storage")


def _write_once(path: Path, payload: dict[str, object], uid: int,
                *, mode: int = 0o600, max_bytes: int = 2048) -> None:
    """Exclusive create + fsync; partial evidence remains fail-closed.

    The journal must stay 0600. Only the non-secret ephemeral hold uses 0644:
    unprivileged Agents/Workers must read it but can never write it.
    """
    if mode not in (0o600, 0o644):
        raise HoldPreparationBlocked("invalid_evidence_mode")
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
             | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")
    if len(data) > max_bytes:
        raise HoldPreparationBlocked("evidence_too_large")
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise HoldPreparationBlocked("existing_evidence_requires_review") from exc
    # On any failure AFTER O_EXCL, leave the inode intact. The reader regards
    # its presence as a block even if the JSON or fsync was incomplete.
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1):
            # Creation always starts private; widen only after content is
            # written so no unprivileged reader observes partial JSON.
            raise HoldPreparationBlocked("untrusted_created_evidence")
        remaining = memoryview(data)
        while remaining:
            sent = os.write(fd, remaining)
            if sent <= 0:
                raise OSError("short journal write")
            remaining = remaining[sent:]
        if mode != 0o600:
            os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(
        path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def prepare_root_only(
    *, transaction_id: str, ttl_seconds: int = 600,
    journal_path: Path = PENDING_PATH, hold_path: Path = HOLD_PATH,
    trusted_uid: int = 0, now: int | None = None,
    release_sha256: str | None = None,
    binding_path: Path = BINDING_PATH,
    expected_agent_ids: list[str] | None = None,
) -> dict[str, object]:
    """Prepare a single pending transaction, with no implicit activation.

    The persistent pending record is fsynced BEFORE the ephemeral /run hold.
    A crash at any point leaves a journal that blocks reconciliation when
    the marker is missing. There is deliberately no cleanup API here.

    Injectable paths/uid are for disposable local tests only; installed
    callers must use the root-owned fixed paths and run as root.
    """
    journal_path, hold_path, binding_path = (
        Path(journal_path), Path(hold_path), Path(binding_path))
    if (os.geteuid() != trusted_uid or not journal_path.is_absolute()
            or not hold_path.is_absolute() or journal_path == hold_path):
        raise HoldPreparationBlocked("root_only_evidence_required")
    if type(transaction_id) is not str or not _ID.fullmatch(transaction_id):
        raise HoldPreparationBlocked("invalid_transaction_id")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
        raise HoldPreparationBlocked("invalid_lease_window")
    if release_sha256 is not None:
        if (type(release_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", release_sha256)
                or binding_path != journal_path.parent / "no-drain-release-binding.json"
                or not binding_path.is_absolute()
                or binding_path in (journal_path, hold_path)):
            raise HoldPreparationBlocked("invalid_release_binding_scope")
    inventory_path = journal_path.parent / "no-drain-agent-inventory.json"
    if expected_agent_ids is not None:
        if (release_sha256 is None or type(expected_agent_ids) is not list
                or not 1 <= len(expected_agent_ids) <= 64
                or any(type(agent) is not str or not _AGENT_ID.fullmatch(agent)
                       for agent in expected_agent_ids)
                or len(set(expected_agent_ids)) != len(expected_agent_ids)
                or inventory_path in (journal_path, hold_path, binding_path)):
            raise HoldPreparationBlocked("invalid_operator_agent_inventory")
        # Copy once; the inventory is supplied by the trusted coordinator,
        # never obtained from a single Agent or its heartbeat receipt.
        expected_agent_ids = sorted(expected_agent_ids)
    started = int(time.time()) if now is None else now
    if type(started) is not int or started <= 0:
        raise HoldPreparationBlocked("invalid_issue_time")

    # No path may be installed under an untrusted directory. Do not create
    # directories, replace files, follow links, unlink or overwrite evidence.
    try:
        _trusted_directory(journal_path.parent, trusted_uid)
        _trusted_directory(hold_path.parent, trusted_uid, runtime_readable=True)
        if release_sha256 is not None:
            _trusted_directory(binding_path.parent, trusted_uid)
    except OSError as exc:
        raise HoldPreparationBlocked("evidence_directory_unavailable") from exc

    expires = started + ttl_seconds
    pending = {
        "kind": "CapivaraDSMNoDrainPendingJournal",
        "schema_version": 1,
        "transaction_id": transaction_id,
        "issued_at": started,
        "expires_at": expires,
        "state": "prepared_requires_distributed_fence",
        "live_no_drain_authorized": False,
    }
    marker = {
        "kind": "CapivaraDSMNoDrainMaintenanceHold",
        "schema_version": 1,
        "transaction_id": transaction_id,
        "issued_at": started,
        "expires_at": expires,
    }
    try:
        # Claim the transaction with the durable recovery sentinel FIRST.
        # An existing journal fails O_EXCL without any modification.
        # Orphaned markers, bindings or inventories must leave this sentinel
        # in place as well, so losing /run cannot silently unblock recovery.
        _write_once(journal_path, pending, trusted_uid)
        paths = [hold_path, journal_path.parent / "no-drain-release-binding.json",
                 inventory_path]
        for evidence in paths:
            try:
                evidence.lstat()
            except FileNotFoundError:
                continue
            raise HoldPreparationBlocked("existing_evidence_requires_review")
        if release_sha256 is not None:
            # Bind operator-pinned release bytes before hold exposure.
            # This SHA is NOT a publisher signature or an update approval.
            _write_once(binding_path, {
                "kind": "CapivaraDSMNoDrainReleaseBinding",
                "schema_version": 1,
                "transaction_id": transaction_id,
                "release_sha256": release_sha256,
                "issued_at": started,
                "expires_at": expires,
                "scope": "root_pinned_release_identity_only",
                "live_no_drain_authorized": False,
            }, trusted_uid, mode=0o644)
        if expected_agent_ids is not None:
            _write_once(inventory_path, {
                "kind": "DSM928OperatorAgentInventory",
                "schema_version": 1,
                "transaction_id": transaction_id,
                "release_sha256": release_sha256,
                "issued_at": started,
                "expires_at": expires,
                "agent_ids": expected_agent_ids,
            }, trusted_uid, max_bytes=16384)
        _write_once(hold_path, marker, trusted_uid, mode=0o644)
    except OSError as exc:
        raise HoldPreparationBlocked("evidence_write_failed_manual_recovery") from exc
    return {
        "status": "persistent_hold_prepared_manual_recovery_required",
        "transaction_id": transaction_id,
        "release_identity_bound_locally": release_sha256 is not None,
        "operator_agent_inventory_persisted": expected_agent_ids is not None,
        "publisher_signature_verified": False,
        "remote_agents_acked": False,
        "controller_http_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }


def _terminal_decision(outcome, journal_sha256):
    if (outcome not in ("verified", "rolled_back", "recovered_rollback")
            or type(journal_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", journal_sha256)):
        raise HoldPreparationBlocked("invalid_terminal_decision")
    return {"outcome": outcome, "journal_sha256": journal_sha256}


def _persist_terminal_receipt(path, payload, uid, *, require_existing=False):
    """Write once, or acknowledge exactly the same durable decision.

    A conflicting or incomplete receipt stays blocking. Never truncate,
    remove or rewrite it, and never clear the maintenance sentinel here.
    """
    _trusted_directory(path.parent, uid)
    expected = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
                + "\n").encode("utf-8")
    if not os.path.lexists(path):
        if require_existing:
            raise HoldPreparationBlocked("original_durable_witness_missing")
        _write_once(path, payload, uid, max_bytes=32768)
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        found = os.fstat(fd)
        if (not stat.S_ISREG(found.st_mode) or found.st_uid != uid
                or stat.S_IMODE(found.st_mode) != 0o600
                or found.st_nlink != 1 or found.st_size != len(expected)
                or (found.st_dev, found.st_ino) != (before.st_dev, before.st_ino)
                or os.read(fd, len(expected) + 1) != expected):
            raise HoldPreparationBlocked("terminal_decision_conflict_or_incomplete")
        named = path.lstat()
        after = os.fstat(fd)
        def fingerprint(item):
            return (item.st_dev, item.st_ino, item.st_uid, item.st_gid,
                    item.st_mode, item.st_nlink, item.st_size,
                    item.st_mtime_ns, item.st_ctime_ns)
        if fingerprint(found) != fingerprint(after) or fingerprint(found) != fingerprint(named):
            raise HoldPreparationBlocked("durable_witness_identity_changed")
        os.fsync(fd)
    finally:
        os.close(fd)
    folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def _require_idle_managed_systemd_work(jobs, units):
    """Reject queued systemd actions and active independent Agent helpers.

    Only the known resident console reader and completed runtime identity
    oneshot may remain active in the helper namespace. This is a negative
    witness for systemd work, not proof of arbitrary external jobs or cron.
    """
    for line in jobs.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4 or not fields[0].isdecimal():
            raise HoldPreparationBlocked("systemd_job_inventory_invalid")
        unit = fields[1]
        if unit.startswith(("capivara-", "dsm-")):
            raise HoldPreparationBlocked("managed_systemd_job_pending:" + unit[:191])
    for line in units.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 4 or fields[1] != "loaded":
            raise HoldPreparationBlocked("agent_helper_unit_inventory_invalid")
        unit, active, sub = fields[0], fields[2], fields[3]
        if not (unit.startswith(("capivara-agent-", "dsm-hybrid-agent-"))
                and unit.endswith((".service", ".timer"))):
            raise HoldPreparationBlocked("unexpected_agent_helper_unit")
        if ((unit, active, sub) not in (
                ("capivara-agent-console-reader.service", "active", "running"),
                ("capivara-agent-runtime-identity.service", "active", "exited"))):
            raise HoldPreparationBlocked("independent_agent_systemd_work_pending:" + unit[:191])


def _check_installed_systemd_work():
    def systemctl(*args):
        result = subprocess.run(
            ("/usr/bin/systemctl", *args), capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_COLORS": "0"},
            check=False, timeout=5)
        if result.returncode != 0 or len(result.stdout) > 262144:
            raise HoldPreparationBlocked("systemd_work_observation_failed")
        return result.stdout

    def jobs():
        return systemctl("list-jobs", "--no-legend", "--no-pager", "--plain")

    def units():
        return systemctl(
            "list-units", "--all", "--no-legend", "--plain", "--no-pager",
            "--state=active,activating,reloading,deactivating",
            "capivara-agent-*.service", "dsm-hybrid-agent-*.service",
            "capivara-agent-uninstall-finalize.timer")

    # Both observations must be clean; a queued action can move from the
    # job inventory into an active helper between the two systemd queries.
    _require_idle_managed_systemd_work(jobs(), units())
    _require_idle_managed_systemd_work(jobs(), units())


def _game_inventory(raw):
    units = []
    for line in raw.splitlines():
        fields = line.split()
        if not fields:
            continue
        if (len(fields) < 4 or not re.fullmatch(
                r"capivara-instance-[A-Za-z0-9_.-]+\.service", fields[0])
                or fields[1:4] != ["loaded", "active", "running"]
                or fields[0] in units):
            raise HoldPreparationBlocked("unstable_or_invalid_managed_game_inventory")
        units.append(fields[0])
    if len(units) > 64:
        raise HoldPreparationBlocked("managed_game_inventory_too_large")
    return sorted(units)


def _installed_game_snapshot():
    """Observe managed games without issuing service actions or reading secrets."""
    def systemctl(*args):
        result = subprocess.run(
            ("/usr/bin/systemctl", *args), capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_COLORS": "0"},
            check=False, timeout=5)
        if result.returncode != 0 or len(result.stdout) > 262144:
            raise HoldPreparationBlocked("managed_game_systemd_observation_failed")
        return result.stdout

    def inventory():
        return _game_inventory(systemctl(
            "list-units", "--type=service", "--all", "--no-legend", "--plain",
            "--no-pager", "--state=active,activating,reloading,deactivating",
            "capivara-instance-*.service"))

    def boot():
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
            raise HoldPreparationBlocked("managed_game_boot_identity_unverified")
        return value

    props = ("ActiveState", "SubState", "MainPID", "ExecMainStartTimestampMonotonic",
             "InvocationID", "ControlGroup", "NRestarts", "FragmentPath",
             "ExecStart", "WorkingDirectory", "PartOf", "BindsTo", "PropagatesStopTo")
    def observe(unit):
        raw = systemctl("show", unit, "--no-pager", "--property=" + ",".join(props))
        values = {}
        for line in raw.splitlines():
            key, sep, value = line.partition("=")
            if not sep or key not in props or key in values:
                raise HoldPreparationBlocked("invalid_managed_game_unit_properties")
            values[key] = value
        if (set(values) != set(props) or values["ActiveState"] != "active"
                or values["SubState"] != "running"
                or not re.fullmatch(r"[1-9][0-9]*", values["MainPID"])
                or not re.fullmatch(r"[1-9][0-9]*", values["ExecMainStartTimestampMonotonic"])
                or not re.fullmatch(r"[0-9a-f]{32}", values["InvocationID"])
                or values["InvocationID"] == "0"*32
                or not values["NRestarts"].isdecimal()
                or not values["ControlGroup"].startswith("/")
                or not values["ExecStart"] or not values["FragmentPath"]):
            raise HoldPreparationBlocked("managed_game_process_identity_unverified")
        pid = int(values["MainPID"])
        if pid <= 1:
            raise HoldPreparationBlocked("managed_game_process_identity_unverified")
        base = Path("/proc") / str(pid)
        raw_stat = (base/"stat").read_text()
        close = raw_stat.rfind(")")
        fields = raw_stat[close+2:].split()
        if (not raw_stat.startswith(str(pid) + " (") or close < 0 or len(fields) < 20
                or fields[0] in ("Z", "X", "x")
                or not fields[19].isdecimal() or int(fields[19]) <= 0):
            raise HoldPreparationBlocked("managed_game_kernel_identity_unverified")
        group = [line.split(":", 2)[2] for line in (base/"cgroup").read_text().splitlines()
                 if line.startswith("0::") or ":name=systemd:" in line]
        if len(group) != 1 or not (group[0] == values["ControlGroup"]
                or group[0].startswith(values["ControlGroup"] + "/")):
            raise HoldPreparationBlocked("managed_game_cgroup_identity_unverified")
        stable = {key: values[key] for key in props if key not in (
            "ActiveState", "SubState", "MainPID", "ExecMainStartTimestampMonotonic",
            "InvocationID", "NRestarts")}
        return {"unit": unit, "pid": pid, "start_ticks": int(fields[19]),
                "start_stamp": int(values["ExecMainStartTimestampMonotonic"]),
                "invocation_id": values["InvocationID"], "restarts": int(values["NRestarts"]),
                "unit_sha256": hashlib.sha256(json.dumps(
                    stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}

    boot_id = boot()
    units = inventory()
    before = [observe(unit) for unit in units]
    if inventory() != units or [observe(unit) for unit in units] != before or boot() != boot_id:
        raise HoldPreparationBlocked("managed_game_identity_changed_during_observation")
    return {"boot_id": boot_id, "units": before}


def _validate_agent_daemon_snapshot(unit, process, *, uid):
    name = "capivara-agent.service"
    if (type(uid) is not int or uid <= 0
            or unit.get("ActiveState") != "active" or unit.get("SubState") != "running"
            or unit.get("User") != "capivara-agent"
            or unit.get("ControlGroup") != "/system.slice/" + name
            or not re.fullmatch(r"[1-9][0-9]*", unit.get("MainPID", ""))
            or not re.fullmatch(r"[0-9a-f]{32}", unit.get("InvocationID", ""))
            or unit["InvocationID"] == "0"*32
            or not re.fullmatch(r"[1-9][0-9]*", unit.get("ExecMainStartTimestampMonotonic", ""))):
        raise HoldPreparationBlocked("installed_agent_unit_identity_unverified")
    args = process.get("argv") or ()
    if (process.get("pid") != int(unit["MainPID"])
            or process.get("pid") <= 1
            or process.get("uid") != uid
            or process.get("cgroup") != unit["ControlGroup"]
            or type(process.get("start_ticks")) is not int or process["start_ticks"] <= 0
            or process.get("finalization_flock_opted_in") is not True
            or len(args) != 2
            or not re.fullmatch(r"python3(?:\.[0-9]+)?", Path(args[0]).name)
            or args[1] != "/opt/capivara-agent/runtime/agent.py"):
        raise HoldPreparationBlocked("installed_agent_process_or_flock_unverified")
    return {"pid": process["pid"], "uid": uid, "start_ticks": process["start_ticks"],
            "invocation_id": unit["InvocationID"],
            "start_stamp": int(unit["ExecMainStartTimestampMonotonic"])}


def _installed_agent_daemon_snapshot():
    """Observe the actual standalone daemon; never infer external-job ACK."""
    import pwd
    uid = pwd.getpwnam("capivara-agent").pw_uid
    props = ("ActiveState", "SubState", "MainPID", "User", "ControlGroup",
             "InvocationID", "ExecMainStartTimestampMonotonic")
    def unit():
        result = subprocess.run(
            ("/usr/bin/systemctl", "show", "capivara-agent.service", "--no-pager",
             "--property=" + ",".join(props)), capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_COLORS": "0"},
            check=False, timeout=5)
        if result.returncode or len(result.stdout) > 16384:
            raise HoldPreparationBlocked("installed_agent_systemd_unavailable")
        values = {}
        for line in result.stdout.splitlines():
            key, sep, value = line.partition("=")
            if not sep or key not in props or key in values:
                raise HoldPreparationBlocked("invalid_installed_agent_unit_properties")
            values[key] = value
        if set(values) != set(props) or not re.fullmatch(r"[1-9][0-9]*", values["MainPID"]):
            raise HoldPreparationBlocked("installed_agent_unit_properties_incomplete")
        return values
    def process(pid):
        base = Path("/proc") / str(pid)
        raw = (base / "stat").read_text()
        close = raw.rfind(")")
        fields = raw[close+2:].split()
        if (close < 0 or not raw.startswith(str(pid) + " (") or len(fields) < 20
                or fields[0] in ("Z", "X", "x")):
            raise HoldPreparationBlocked("installed_agent_kernel_identity_unverified")
        uids = [line.split()[1:] for line in (base / "status").read_text().splitlines()
                if line.startswith("Uid:")]
        if len(uids) != 1 or uids[0] != [str(uid)]*4:
            raise HoldPreparationBlocked("installed_agent_uid_unverified")
        groups = [line.split(":", 2)[2] for line in (base / "cgroup").read_text().splitlines()
                  if line.startswith("0::") or ":name=systemd:" in line]
        argv = (base / "cmdline").read_bytes()
        env = (base / "environ").read_bytes()
        if (len(groups) != 1 or not argv.endswith(b"\x00") or len(argv) > 16384
                or not env.endswith(b"\x00") or len(env) > 262144):
            raise HoldPreparationBlocked("installed_agent_process_observation_incomplete")
        optin = [entry for entry in env[:-1].split(b"\x00")
                 if entry.startswith(b"DSM928_AGENT_FINALIZATION_FLOCK=")]
        return {"pid": pid, "uid": uid, "start_ticks": int(fields[19]),
                "cgroup": groups[0],
                "argv": tuple(x.decode("utf-8") for x in argv[:-1].split(b"\x00")),
                "finalization_flock_opted_in": optin == [b"DSM928_AGENT_FINALIZATION_FLOCK=1"]}
    try:
        first = unit()
        pid = int(first["MainPID"])
        before, after = process(pid), process(pid)
        if first != unit() or before != after:
            raise HoldPreparationBlocked("installed_agent_daemon_identity_changed")
        return _validate_agent_daemon_snapshot(first, before, uid=uid)
    except (OSError, ValueError, KeyError, LookupError, subprocess.SubprocessError) as exc:
        raise HoldPreparationBlocked("installed_agent_daemon_observation_failed") from exc


def _retain_installed_agent_daemon_witness(*, pending, transaction_id, release_sha256,
                                           agent_id, recover_existing, initial):
    path = Path(pending).parent / ("agent-daemon-witness-" + transaction_id + ".json")
    payload = {"kind": "DSM928InstalledStandaloneAgentWitness", "schema_version": 1,
               "transaction_id": transaction_id, "release_sha256": release_sha256,
               "agent_id": agent_id, "snapshot": initial, "live_no_drain_authorized": False}
    if not recover_existing and os.path.lexists(path):
        raise HoldPreparationBlocked("existing_agent_daemon_witness_requires_review")
    if _installed_agent_daemon_snapshot() != initial:
        raise HoldPreparationBlocked("installed_agent_daemon_identity_changed")
    _persist_terminal_receipt(path, payload, 0, require_existing=recover_existing)
    def checkpoint():
        if _installed_agent_daemon_snapshot() != initial:
            raise HoldPreparationBlocked("installed_agent_daemon_identity_changed")
        _persist_terminal_receipt(path, payload, 0, require_existing=True)
    return checkpoint


def _retain_installed_game_witness(*, pending, transaction_id, release_sha256,
                                   agent_id, recover_existing, initial):
    """Persist the ORIGINAL boot/PID witness; never establish a new baseline on recovery."""
    path = Path(pending).parent / ("game-witness-" + transaction_id + ".json")
    payload = {"kind": "DSM928InstalledGameIdentityWitness", "schema_version": 1,
               "transaction_id": transaction_id, "release_sha256": release_sha256,
               "agent_id": agent_id, "snapshot": initial,
               "live_no_drain_authorized": False}
    if recover_existing and not os.path.lexists(path):
        raise HoldPreparationBlocked("original_installed_game_witness_missing")
    if not recover_existing and os.path.lexists(path):
        raise HoldPreparationBlocked("existing_installed_game_witness_requires_review")
    if _installed_game_snapshot() != initial:
        raise HoldPreparationBlocked("installed_game_identity_changed_before_binding")
    _persist_terminal_receipt(path, payload, 0, require_existing=recover_existing)
    def checkpoint():
        if _installed_game_snapshot() != initial:
            raise HoldPreparationBlocked("installed_game_identity_changed")
        # Read back exact original bytes; this must never recreate a lost witness.
        if not os.path.lexists(path):
            raise HoldPreparationBlocked("original_installed_game_witness_missing")
        _persist_terminal_receipt(path, payload, 0, require_existing=True)
    return checkpoint


def _installed_confirmation(scope, local_hybrid_agent_id, recorded_agent_ids,
                            outcome, journal_sha256):
    """The authenticated coordinator must confirm every participant, not a subset."""
    decision = _terminal_decision(outcome, journal_sha256)
    ids = scope["expected_agent_ids"]
    if (type(recorded_agent_ids) is not list or recorded_agent_ids != ids
            or type(local_hybrid_agent_id) is not str
            or local_hybrid_agent_id not in ids):
        raise HoldPreparationBlocked("installed_terminal_inventory_incomplete")
    return {
        "kind": "DSM928InstalledDistributedTerminalConfirmation",
        "schema_version": 1,
        "transaction_id": scope["transaction_id"],
        "release_sha256": scope["release_sha256"],
        "issued_at": scope["issued_at"], "expires_at": scope["expires_at"],
        "local_hybrid_agent_id": local_hybrid_agent_id,
        "recorded_agent_ids": ids.copy(), **decision,
        "live_no_drain_authorized": False,
    }


def _validate_installed_confirmation(confirmation, scope, decision):
    if type(confirmation) is not dict:
        raise HoldPreparationBlocked("installed_terminal_confirmation_invalid")
    expected = _installed_confirmation(
        scope, confirmation.get("local_hybrid_agent_id"),
        confirmation.get("recorded_agent_ids"), **decision)
    raw = (json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n").encode()
    actual = (json.dumps(confirmation, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if actual != raw:
        raise HoldPreparationBlocked("installed_terminal_confirmation_mismatch")
    return hashlib.sha256(raw).hexdigest()


def _agent_terminal_payload(scope, agent_id, decision):
    return {"kind": "DSM928AgentTerminalDecision", "schema_version": 1,
            **scope, "agent_id": agent_id, **decision,
            "live_no_drain_authorized": False, "pending_evidence_retained": True}


def _archive_fixture_hold(*, marker, pending, transaction_id, decision, uid, checkpoint):
    """Archive exact evidence before clearing a disposable, confirmed hold.

    The persistent sentinel is removed LAST. An interruption before that
    point remains fail-closed. Never call on installed paths; a partially
    released distributed fixture still requires operator reconciliation.
    """
    import tempfile
    import hashlib
    marker, pending = Path(marker), Path(pending)
    tmp = Path(tempfile.gettempdir()).resolve(strict=True)
    if (os.geteuid() != uid or tmp not in marker.parents or tmp not in pending.parents
            or marker == HOLD_PATH or pending == PENDING_PATH
            or not _ID.fullmatch(transaction_id)):
        raise HoldPreparationBlocked("fixture_terminal_release_only")
    return _archive_confirmed_hold(
        marker=marker, pending=pending, transaction_id=transaction_id,
        decision=decision, uid=uid, checkpoint=checkpoint, installed=False)


def _archive_confirmed_hold(*, marker, pending, transaction_id, decision,
                            uid, checkpoint, installed):
    paths = [marker, pending.parent / "no-drain-release-binding.json",
             pending.parent / "no-drain-agent-inventory.json", pending]
    checkpoint()
    records = {}
    for path in paths:
        _trusted_directory(path.parent, uid)
        found = path.lstat()
        if (not stat.S_ISREG(found.st_mode) or found.st_uid != uid
                or found.st_nlink != 1 or found.st_mode & 0o022
                or not 0 < found.st_size <= 16384):
            raise HoldPreparationBlocked("terminal_archive_evidence_untrusted")
        raw = path.read_bytes()
        if len(raw) != found.st_size:
            raise HoldPreparationBlocked("terminal_archive_evidence_changed")
        records[path.name] = {"sha256": hashlib.sha256(raw).hexdigest(),
                              "content": raw.decode("utf-8")}
    checkpoint()
    archive = pending.parent / ("released-" + transaction_id + ".json")
    _persist_terminal_receipt(archive, {
        "kind": ("DSM928ArchivedInstalledHold" if installed
                 else "DSM928ArchivedFixtureHold"), "schema_version": 1,
        "transaction_id": transaction_id, **decision,
        "evidence": records, "live_no_drain_authorized": False}, uid)
    checkpoint()
    for path in paths:
        path.unlink()
        folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    return {("installed_hold_released" if installed else "fixture_hold_released"): True,
            "live_no_drain_authorized": False}


def _release_confirmed_installed_hold(*, scope, agent_id, confirmation, decision, checkpoint):
    """Fixed-path finalization primitive; only under the original retained locks.

    The caller must already have independently verified the terminal product
    journal. No new terminal decision can be manufactured by this function.
    A partial release still requires explicit administrative reconciliation.
    """
    if os.geteuid() != 0 or agent_id not in scope["expected_agent_ids"]:
        raise HoldPreparationBlocked("installed_terminal_release_requires_root")
    confirmation_sha = _validate_installed_confirmation(confirmation, scope, decision)
    checkpoint()
    tx = scope["transaction_id"]
    if not _ID.fullmatch(tx):
        raise HoldPreparationBlocked("invalid_installed_terminal_transaction")
    terminal = PENDING_PATH.parent / ("terminal-" + tx + ".json")
    witness = PENDING_PATH.parent / ("game-witness-" + tx + ".json")
    if not os.path.lexists(terminal) or not os.path.lexists(witness):
        raise HoldPreparationBlocked("installed_terminal_or_game_witness_missing")
    _persist_terminal_receipt(terminal, _agent_terminal_payload(scope, agent_id, decision), 0)
    # Persist the full confirmation locally before clearing any sentinel.
    _persist_terminal_receipt(PENDING_PATH.parent / ("terminal-confirmation-" + tx + ".json"),
                              confirmation, 0)
    checkpoint()
    return _archive_confirmed_hold(
        marker=HOLD_PATH, pending=PENDING_PATH, transaction_id=tx,
        decision={**decision, "confirmation_sha256": confirmation_sha},
        uid=0, checkpoint=checkpoint, installed=True)


@contextmanager
def prepare_standalone_agent_scope(
    *, transaction_id: str, release_sha256: str, issued_at: int,
    expires_at: int, expected_agent_ids: list[str], local_agent_id: str,
    hold_path: Path = HOLD_PATH, journal_path: Path = PENDING_PATH,
    privileged_lock_path: Path | None = None,
    finalization_lock_path: Path | None = None,
    trusted_uid: int = 0, fixture_root: Path | None = None,
    fixture_group_gid: int | None = None, now: int | None = None,
    recover_existing: bool = False,
) -> Iterator[dict[str, object]]:
    """Root operator's host-local PREPARE for a shared distributed transaction.

    All hosts receive the SAME operator-reviewed transaction, package digest,
    full inventory and absolute time window. Acquire both existing exclusive
    lock families BEFORE writing persistent evidence. The context owns the
    locks until exit; the pending journal stays blocking even after exit,
    interruption or reboot. This is neither a Controller ACK nor a commit,
    and does not claim that uninstrumented jobs or other hosts are fenced.
    No installed caller or network endpoint invokes this automatically.
    """
    from game_uptime_privileged_flock import (
        LOCK_PATH as HELPER_LOCK, exclusive_privileged_helper_lock,
        exclusive_update_admission,
    )
    from game_uptime_finalization_flock import (
        LOCK_PATH as CHILD_LOCK, exclusive_finalization_lock,
    )
    from game_uptime_maintenance_hold import observe
    from game_uptime_transaction_binding import binding_for_hold
    from game_uptime_privileged_journal_witness import _verify_snapshot
    from game_uptime_wire_replay_service import read_inventory

    marker, pending = Path(hold_path), Path(journal_path)
    helper = HELPER_LOCK if privileged_lock_path is None else Path(privileged_lock_path)
    child = CHILD_LOCK if finalization_lock_path is None else Path(finalization_lock_path)
    when = int(time.time()) if now is None else now
    if (os.geteuid() != trusted_uid
            or type(recover_existing) is not bool
            or type(transaction_id) is not str or not _ID.fullmatch(transaction_id)
            or type(release_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", release_sha256)
            or type(issued_at) is not int or type(expires_at) is not int
            or not 0 < issued_at <= when < expires_at <= issued_at + 900
            or type(expected_agent_ids) is not list or not 1 <= len(expected_agent_ids) <= 64
            or any(type(agent) is not str or not _AGENT_ID.fullmatch(agent)
                   for agent in expected_agent_ids)
            or len(set(expected_agent_ids)) != len(expected_agent_ids)
            or type(local_agent_id) is not str or local_agent_id not in expected_agent_ids):
        raise HoldPreparationBlocked("invalid_shared_agent_prepare_scope")
    ids = sorted(expected_agent_ids)
    if fixture_root is None:
        if (trusted_uid != 0 or now is not None or fixture_group_gid is not None
                or (marker, pending, helper, child) !=
                   (HOLD_PATH, PENDING_PATH, HELPER_LOCK, CHILD_LOCK)):
            raise HoldPreparationBlocked("installed_agent_prepare_requires_root_fixed_paths")
        child_identity = {}
    else:
        import tempfile
        root = Path(fixture_root)
        temp = Path(tempfile.gettempdir()).resolve(strict=True)
        if (root.is_symlink() or not root.is_dir() or not root.is_absolute()
                or root.resolve(strict=True) != root or temp not in root.parents
                or root.stat().st_uid != trusted_uid or root.stat().st_mode & 0o022
                or type(fixture_group_gid) is not int
                or any(root not in p.parents for p in (marker, pending, helper, child))):
            raise HoldPreparationBlocked("disposable_agent_prepare_scope_required")
        child_identity = {"trusted_uid": trusted_uid, "group_gid": fixture_group_gid}
    binding = pending.parent / "no-drain-release-binding.json"
    inventory = pending.parent / "no-drain-agent-inventory.json"
    if len({marker, pending, binding, inventory, helper, child}) != 6:
        raise HoldPreparationBlocked("agent_prepare_path_collision")
    def identity(path):
        meta = path.lstat()
        return (meta.st_dev, meta.st_ino, meta.st_uid, meta.st_gid, meta.st_mode,
                meta.st_nlink, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)
    with ExitStack() as stack:
        try:
            if fixture_root is None:
                stack.enter_context(exclusive_update_admission())
            locks = (identity(helper), identity(child))
            # Same acquisition order as the existing two-family witness.
            stack.enter_context(exclusive_finalization_lock(path=child, **child_identity))
            stack.enter_context(exclusive_privileged_helper_lock(path=helper, trusted_uid=trusted_uid))
            if (identity(helper), identity(child)) != locks:
                raise HoldPreparationBlocked("agent_prepare_lock_changed")
            current = int(time.time()) if now is None else now
            if not issued_at <= current < expires_at:
                raise HoldPreparationBlocked("shared_agent_prepare_window_expired")
            if fixture_root is None:
                _check_installed_systemd_work()
            initial_games = _installed_game_snapshot() if fixture_root is None else None
            initial_agent = _installed_agent_daemon_snapshot() if fixture_root is None else None
            # Recovery is an explicit read-only reacquisition of an intact,
            # unexpired scope. Never recreate a lost marker, renew a lease,
            # repair a partial journal or call PREPARE on a recovery request.
            if not recover_existing:
                prepare_root_only(
                    transaction_id=transaction_id, ttl_seconds=expires_at-issued_at,
                    journal_path=pending, hold_path=marker, trusted_uid=trusted_uid,
                    now=issued_at, release_sha256=release_sha256,
                    binding_path=binding, expected_agent_ids=ids)
            paths = (marker, pending, binding, inventory, helper, child)
            pins = tuple(identity(path) for path in paths)
            game_checkpoint = None
            daemon_checkpoint = None
            if fixture_root is None:
                daemon_checkpoint = _retain_installed_agent_daemon_witness(
                    pending=pending, transaction_id=transaction_id,
                    release_sha256=release_sha256, agent_id=local_agent_id,
                    recover_existing=recover_existing, initial=initial_agent)
                game_checkpoint = _retain_installed_game_witness(
                    pending=pending, transaction_id=transaction_id,
                    release_sha256=release_sha256, agent_id=local_agent_id,
                    recover_existing=recover_existing, initial=initial_games)

            retained = True
            def checkpoint():
                if not retained:
                    raise HoldPreparationBlocked("agent_scope_no_longer_retained")
                current = int(time.time()) if now is None else now
                expected = (transaction_id, issued_at, expires_at)
                if _verify_snapshot(
                        expected_transaction_id=transaction_id, hold_path=marker,
                        journal_path=pending, trusted_uid=trusted_uid, now=current) != expected:
                    raise HoldPreparationBlocked("shared_agent_prepare_lease_changed")
                observed = observe(path=marker, pending_path=pending,
                                   trusted_uid=trusted_uid, now=current)
                pin = binding_for_hold(observed, path=binding,
                                       trusted_uid=trusted_uid, now=current)
                expected_inventory = {
                    "kind": "DSM928OperatorAgentInventory", "schema_version": 1,
                    "transaction_id": transaction_id, "release_sha256": release_sha256,
                    "issued_at": issued_at, "expires_at": expires_at, "agent_ids": ids,
                }
                if (not pin or pin.get("release_sha256") != release_sha256
                        or read_inventory(path=inventory, trusted_uid=trusted_uid) != expected_inventory
                        or tuple(identity(path) for path in paths) != pins):
                    raise HoldPreparationBlocked("shared_agent_prepare_evidence_changed")
                if game_checkpoint is not None:
                    game_checkpoint()
                if daemon_checkpoint is not None:
                    daemon_checkpoint()
                    _check_installed_systemd_work()
            checkpoint()
        except (OSError, RuntimeError, ValueError) as exc:
            raise HoldPreparationBlocked("standalone_agent_prepare_blocked") from exc

        terminal_recorded = None
        terminal_scope = {"transaction_id": transaction_id, "release_sha256": release_sha256,
                          "issued_at": issued_at, "expires_at": expires_at,
                          "expected_agent_ids": ids}

        def record_terminal(outcome, journal_sha256):
            nonlocal terminal_recorded
            decision = _terminal_decision(outcome, journal_sha256)
            checkpoint()
            _persist_terminal_receipt(
                pending.parent / ("terminal-" + transaction_id + ".json"),
                _agent_terminal_payload(terminal_scope, local_agent_id, decision), trusted_uid)
            checkpoint()
            terminal_recorded = decision
            return decision

        released = False

        def release_fixture(outcome, journal_sha256, confirmation_sha256):
            nonlocal released
            if fixture_root is None or released:
                raise HoldPreparationBlocked("fixture_terminal_release_only")
            if (type(confirmation_sha256) is not str
                    or not re.fullmatch(r"[0-9a-f]{64}", confirmation_sha256)):
                raise HoldPreparationBlocked("invalid_global_confirmation_digest")
            decision = record_terminal(outcome, journal_sha256)
            result = _archive_fixture_hold(
                marker=marker, pending=pending, transaction_id=transaction_id,
                decision={**decision, "confirmation_sha256": confirmation_sha256},
                uid=trusted_uid, checkpoint=checkpoint)
            released = True
            return result

        def release_installed(confirmation):
            nonlocal released
            if (fixture_root is not None or released or not recover_existing
                    or terminal_recorded is None):
                raise HoldPreparationBlocked("reviewed_installed_terminal_release_required")
            if confirmation.get("local_hybrid_agent_id") == local_agent_id:
                raise HoldPreparationBlocked("standalone_agent_cannot_be_local_hybrid")
            result = _release_confirmed_installed_hold(
                scope=terminal_scope, agent_id=local_agent_id,
                confirmation=confirmation, decision=terminal_recorded,
                checkpoint=checkpoint)
            released = True
            return result

        try:
            yield {
                "status": "standalone_agent_prepared_local_scope_retained",
                "agent_id": local_agent_id, "transaction_id": transaction_id,
                "release_sha256": release_sha256, "issued_at": issued_at,
                "expires_at": expires_at, "expected_agent_ids": ids,
                "persistent_journal_prepared": True,
                "recovery_scope_only": recover_existing,
                "cooperating_local_lock_families_retained": 2,
                "checkpoint": checkpoint, "record_terminal": record_terminal,
                "release_fixture": release_fixture,
                "release_installed": release_installed,
                "remote_agents_acked": False, "external_jobs_acked": False,
                "live_no_drain_authorized": False,
            }
            if not released:
                checkpoint()
        finally:
            retained = False


_SESSION_PROTOCOL = "dsm928-retained-agent-scope-v1"
_SESSION_MAX = 16384


def _session_bytes(message: dict) -> bytes:
    raw = (json.dumps(message, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    if len(raw) > _SESSION_MAX:
        raise HoldPreparationBlocked("agent_session_frame_too_large")
    return raw


def _session_read(fd: int, deadline: float) -> dict:
    """Bounded one-frame read on a dedicated pipe/socket, no buffered read."""
    buf = bytearray()
    while len(buf) < _SESSION_MAX:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise HoldPreparationBlocked("agent_session_timeout")
        block = os.read(fd, min(4096, _SESSION_MAX - len(buf)))
        if not block:
            raise HoldPreparationBlocked("agent_session_disconnected")
        buf.extend(block)
        if b"\n" in buf:
            if buf.count(b"\n") != 1 or not buf.endswith(b"\n"):
                raise HoldPreparationBlocked("agent_session_unexpected_frame")
            doc = json.loads(buf)
            if not isinstance(doc, dict) or _session_bytes(doc) != bytes(buf):
                raise HoldPreparationBlocked("agent_session_noncanonical_frame")
            return doc
    raise HoldPreparationBlocked("agent_session_frame_too_large")


def _session_write(fd: int, message: dict, deadline: float):
    raw = memoryview(_session_bytes(message))
    while raw:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
            raise HoldPreparationBlocked("agent_session_timeout")
        sent = os.write(fd, raw[:4096])
        if sent <= 0:
            raise HoldPreparationBlocked("agent_session_disconnected")
        raw = raw[sent:]


def _session_scope(transaction_id, release_sha256, issued_at, expires_at, ids):
    if (type(transaction_id) is not str or not _ID.fullmatch(transaction_id)
            or type(release_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", release_sha256)
            or type(issued_at) is not int or type(expires_at) is not int
            or not 0 < issued_at < expires_at <= issued_at + 900
            or type(ids) is not list or not 1 <= len(ids) <= 64
            or any(type(x) is not str or not _AGENT_ID.fullmatch(x) for x in ids)
            or len(set(ids)) != len(ids)):
        raise HoldPreparationBlocked("invalid_distributed_session_scope")
    return {"transaction_id": transaction_id, "release_sha256": release_sha256,
            "issued_at": issued_at, "expires_at": expires_at,
            "expected_agent_ids": sorted(ids)}


def _retained_session_deadline(scope, clock, *, monotonic=None):
    """Bind a retained session to both wall and monotonic expiry.

    An idle apply/rollback must not discard a cooperating fence after an
    arbitrary frame timeout. A backward wall-clock adjustment must not
    extend the original lease either. Only individual exchanges are
    bounded by a short transport timeout; idle reads end at lease expiry.
    """
    tick = time.monotonic if monotonic is None else monotonic
    current = clock()
    if not scope["issued_at"] <= current < scope["expires_at"]:
        raise HoldPreparationBlocked("retained_session_window_expired")
    hard_end = tick() + scope["expires_at"] - current

    def deadline(max_wait=None):
        current = clock()
        now_tick = tick()
        remaining = min(scope["expires_at"] - current, hard_end - now_tick)
        if current < scope["issued_at"] or remaining <= 0:
            raise HoldPreparationBlocked("retained_session_window_expired")
        return now_tick + (remaining if max_wait is None else min(max_wait, remaining))
    return deadline


def serve_prepared_agent_session(read_fd: int, write_fd: int, *,
                                 local_agent_id: str,
                                 scope_factory=prepare_standalone_agent_scope,
                                 now=None):
    """Serve a dedicated operator-authenticated channel, not public HTTP.

    The caller must independently authenticate the peer and pin local Agent
    identity. The scope factory is injectable for disposable testing only.
    PREPARE retains both actual lock families until CLOSE, EOF or expiry;
    no messages clear durable evidence, update files or authorize no-drain.
    """
    if scope_factory is not prepare_standalone_agent_scope and now is None:
        raise HoldPreparationBlocked("fixture_session_clock_required")
    clock = time.time if now is None else now
    deadline = time.monotonic() + 10
    request = _session_read(read_fd, deadline)
    # A dedicated authenticated connectivity probe must not take locks or
    # write durable maintenance state. It is not a PREPARE or readiness ACK.
    if request.get("action") == "probe":
        challenge = request.get("challenge")
        if (set(request) != {"protocol", "action", "agent_id", "challenge"}
                or request.get("protocol") != _SESSION_PROTOCOL
                or request.get("agent_id") != local_agent_id
                or type(challenge) is not str or not _ID.fullmatch(challenge)):
            raise HoldPreparationBlocked("agent_session_probe_invalid")
        _session_write(write_fd, {
            **request, "action": "probe_received",
            "maintenance_state_changed": False,
            "remote_agents_acked": False, "live_no_drain_authorized": False,
        }, deadline)
        return
    fields = {"transaction_id", "release_sha256", "issued_at", "expires_at", "expected_agent_ids"}
    if (set(request) != fields | {"protocol", "action", "agent_id", "challenge"}
            or request.get("protocol") != _SESSION_PROTOCOL
            or request.get("action") not in ("prepare", "recover")
            or request.get("agent_id") != local_agent_id
            or type(request.get("challenge")) is not str
            or not _ID.fullmatch(request["challenge"])):
        raise HoldPreparationBlocked("agent_session_prepare_invalid")
    scope = _session_scope(**{**{k: request[k] for k in fields if k != "expected_agent_ids"},
                              "ids": request["expected_agent_ids"]})
    if not scope["issued_at"] <= clock() < scope["expires_at"]:
        raise HoldPreparationBlocked("agent_session_window_expired")
    if local_agent_id not in scope["expected_agent_ids"]:
        raise HoldPreparationBlocked("agent_session_identity_not_expected")
    session = secrets.token_hex(16)
    seen = {request["challenge"]}
    frame_deadline = _retained_session_deadline(scope, clock)
    recovering = request["action"] == "recover"
    with scope_factory(local_agent_id=local_agent_id, recover_existing=recovering,
                       **scope) as lease:
        if (lease.get("agent_id") != local_agent_id
                or any(lease.get(k) != v for k, v in scope.items())
                or lease.get("persistent_journal_prepared") is not True
                or lease.get("recovery_scope_only") is not recovering
                or lease.get("cooperating_local_lock_families_retained") != 2
                or lease.get("live_no_drain_authorized") is not False
                or not callable(lease.get("checkpoint"))):
            raise HoldPreparationBlocked("agent_session_local_witness_invalid")
        def answer(action, challenge, decision=None):
            frame_deadline()
            if action not in ("fixture_released", "installed_released"):
                lease["checkpoint"]()
            _session_write(write_fd, {
                **scope, "protocol": _SESSION_PROTOCOL, "action": action,
                "agent_id": local_agent_id, "challenge": challenge,
                "session_id": session, "persistent_journal_prepared": True,
                "recovery_scope_only": recovering,
                "cooperating_local_lock_families_retained": 2,
                "external_jobs_acked": False, "remote_agents_acked": False,
                "live_no_drain_authorized": False,
                **(decision or {}),
            }, frame_deadline(10))
        answer("recovered" if recovering else "prepared", request["challenge"])
        while True:
            req = _session_read(read_fd, frame_deadline())
            frame_deadline()
            challenge = req.get("challenge")
            terminal = req.get("action") == "record_terminal"
            release = req.get("action") == "release_fixture"
            installed_release = req.get("action") == "release_installed"
            extra = {"outcome", "journal_sha256"} if terminal or release else set()
            if release:
                extra.add("confirmation_sha256")
            if installed_release:
                extra.add("confirmation")
            if (set(req) != {"protocol", "action", "session_id", "challenge"} | extra
                    or req.get("protocol") != _SESSION_PROTOCOL
                    or req.get("session_id") != session
                    or req.get("action") not in (
                        "checkpoint", "close", "record_terminal", "release_fixture",
                        "release_installed")
                    or type(challenge) is not str or not _ID.fullmatch(challenge)
                    or challenge in seen or len(seen) >= 4096):
                raise HoldPreparationBlocked("agent_session_challenge_invalid")
            seen.add(challenge)
            if installed_release:
                if not recovering or not callable(lease.get("release_installed")):
                    raise HoldPreparationBlocked("installed_terminal_release_unavailable")
                confirmation = req["confirmation"]
                if type(confirmation) is not dict:
                    raise HoldPreparationBlocked("installed_terminal_confirmation_invalid")
                decision = _terminal_decision(confirmation.get("outcome"),
                                              confirmation.get("journal_sha256"))
                digest = _validate_installed_confirmation(confirmation, scope, decision)
                result = lease["release_installed"](confirmation)
                if result != {"installed_hold_released": True, "live_no_drain_authorized": False}:
                    raise HoldPreparationBlocked("installed_release_receipt_invalid")
                answer("installed_released", challenge, {"confirmation_sha256": digest})
                return
            if release:
                if not callable(lease.get("release_fixture")):
                    raise HoldPreparationBlocked("fixture_terminal_release_unavailable")
                decision = _terminal_decision(req["outcome"], req["journal_sha256"])
                decision["confirmation_sha256"] = req["confirmation_sha256"]
                result = lease["release_fixture"](**decision)
                if result != {"fixture_hold_released": True, "live_no_drain_authorized": False}:
                    raise HoldPreparationBlocked("fixture_release_receipt_invalid")
                answer("fixture_released", challenge, decision)
                return
            if terminal:
                if not callable(lease.get("record_terminal")):
                    raise HoldPreparationBlocked("terminal_decision_storage_unavailable")
                decision = _terminal_decision(req["outcome"], req["journal_sha256"])
                frame_deadline()
                if lease["record_terminal"](**decision) != decision:
                    raise HoldPreparationBlocked("terminal_decision_receipt_invalid")
                answer("terminal_recorded", challenge, decision)
            else:
                answer("closed" if req["action"] == "close" else "retained", challenge)
            if req["action"] == "close":
                return


def probe_agent_session(read_fd: int, write_fd: int, *, agent_id: str):
    """Challenge an already authenticated dedicated channel without PREPARE."""
    if type(agent_id) is not str or not _AGENT_ID.fullmatch(agent_id):
        raise HoldPreparationBlocked("invalid_probe_agent_identity")
    request = {"protocol": _SESSION_PROTOCOL, "action": "probe",
               "agent_id": agent_id, "challenge": secrets.token_hex(16)}
    deadline = time.monotonic() + 10
    _session_write(write_fd, request, deadline)
    reply = _session_read(read_fd, deadline)
    expected = {**request, "action": "probe_received",
                "maintenance_state_changed": False,
                "remote_agents_acked": False, "live_no_drain_authorized": False}
    if _session_bytes(reply) != _session_bytes(expected):
        raise HoldPreparationBlocked("agent_session_probe_receipt_invalid")
    return {"agent_id": agent_id, "protocol_probe_verified": True,
            "maintenance_state_changed": False,
            "remote_agents_acked": False, "live_no_drain_authorized": False}


@contextmanager
def retain_distributed_agent_sessions(*, transaction_id: str, release_sha256: str,
                                      issued_at: int, expires_at: int,
                                      expected_agent_ids: list[str],
                                      session_openers: dict,
                                      local_hybrid_agent_id: str | None = None,
                                      recover_existing: bool = False,
                                      operator_reviewed: bool = False,
                                      now=None) -> Iterator[dict]:
    """Central coordinator for independently authenticated, dedicated sessions.

    A trusted operator must supply one authenticated channel opener for EACH
    pinned standalone Agent. The explicitly pinned Hybrid identity remains
    in the full inventory transmitted to every host, but is covered locally.
    No discovery from receipts and no offline-agent exemption.
    Each opener is a context manager yielding (read_fd, write_fd). This
    protocol does not establish SSH/TLS trust itself, and cannot attest
    uninstrumented jobs, Hybrid coverage or live update authorization.
    No production updater invokes it. Partial prepare leaves journals for
    recovery rather than silently undoing a hold.
    """
    scope = _session_scope(transaction_id, release_sha256, issued_at,
                           expires_at, expected_agent_ids)
    full_ids = scope["expected_agent_ids"]
    if local_hybrid_agent_id is not None and (
            type(local_hybrid_agent_id) is not str or local_hybrid_agent_id not in full_ids):
        raise HoldPreparationBlocked("distributed_hybrid_identity_not_in_inventory")
    ids = [agent for agent in full_ids if agent != local_hybrid_agent_id]
    if not ids:
        raise HoldPreparationBlocked("distributed_standalone_inventory_empty")
    if (type(recover_existing) is not bool or type(operator_reviewed) is not bool
            or (recover_existing and not operator_reviewed)):
        raise HoldPreparationBlocked("explicit_distributed_recovery_review_required")
    initial_action = "recover" if recover_existing else "prepare"
    if (type(session_openers) is not dict or set(session_openers) != set(ids)
            or any(not callable(opener) for opener in session_openers.values())):
        raise HoldPreparationBlocked("distributed_agent_session_inventory_incomplete")
    clock = time.time if now is None else now
    sessions = {}
    active = True
    session_deadline = _retained_session_deadline(scope, clock)
    def deadline():
        return session_deadline(10)
    def exchange(agent, action, decision=None):
        read_fd, write_fd, session = sessions[agent]
        challenge = secrets.token_hex(16)
        request = {"protocol": _SESSION_PROTOCOL, "action": action, "challenge": challenge}
        if action == initial_action:
            request.update(scope, agent_id=agent)
        else:
            request["session_id"] = session
        if decision is not None:
            request.update(decision)
        limit = deadline()
        _session_write(write_fd, request, limit)
        reply = _session_read(read_fd, limit)
        session_deadline()
        session_id = reply.get("session_id")
        response_decision = decision
        if action == "release_installed":
            confirmation = decision["confirmation"]
            response_decision = {"confirmation_sha256": _validate_installed_confirmation(
                confirmation, scope, terminal_recorded)}
        expected = {
            **scope, "protocol": _SESSION_PROTOCOL,
            "action": {"prepare": "prepared", "recover": "recovered",
                       "checkpoint": "retained", "close": "closed",
                       "record_terminal": "terminal_recorded",
                       "release_fixture": "fixture_released",
                       "release_installed": "installed_released"}[action],
            "agent_id": agent, "challenge": challenge, "session_id": session_id,
            "persistent_journal_prepared": True, "recovery_scope_only": recover_existing,
            "cooperating_local_lock_families_retained": 2,
            "external_jobs_acked": False, "remote_agents_acked": False,
            "live_no_drain_authorized": False, **(response_decision or {}),
        }
        if (_session_bytes(reply) != _session_bytes(expected)
                or type(session_id) is not str or not _ID.fullmatch(session_id)
                or (session is not None and session_id != session)
                or (action == initial_action and any(
                    old_session == session_id for _, _, old_session in sessions.values()))):
            raise HoldPreparationBlocked("distributed_agent_session_receipt_invalid")
        sessions[agent] = (read_fd, write_fd, session_id)
    def checkpoint():
        nonlocal active
        if not active or set(sessions) != set(ids):
            raise HoldPreparationBlocked("distributed_agent_session_not_retained")
        try:
            for agent in ids:
                exchange(agent, "checkpoint")
        except (OSError, ValueError, RuntimeError) as exc:
            active = False
            raise HoldPreparationBlocked("distributed_agent_checkpoint_blocked") from exc

    def record_terminal(outcome, journal_sha256):
        nonlocal active, terminal_recorded
        decision = _terminal_decision(outcome, journal_sha256)
        checkpoint()
        try:
            for agent in ids:
                exchange(agent, "record_terminal", decision)
            checkpoint()
        except (OSError, RuntimeError, ValueError) as exc:
            active = False
            raise HoldPreparationBlocked("distributed_terminal_decision_incomplete") from exc
        terminal_recorded = decision
        return {"recorded_agent_ids": ids.copy(), **decision,
                "pending_evidence_retained": True, "live_no_drain_authorized": False}

    released = False
    terminal_recorded = None

    def release_fixture(outcome, journal_sha256, confirmation_sha256):
        nonlocal active, released
        decision = _terminal_decision(outcome, journal_sha256)
        if terminal_recorded != decision:
            raise HoldPreparationBlocked("global_terminal_record_required")
        if (type(confirmation_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", confirmation_sha256)):
            raise HoldPreparationBlocked("invalid_global_confirmation_digest")
        checkpoint()
        try:
            for agent in ids:
                exchange(agent, "release_fixture",
                         {**decision, "confirmation_sha256": confirmation_sha256})
        except (OSError, RuntimeError, ValueError) as exc:
            active = False
            raise HoldPreparationBlocked("partial_fixture_release_requires_review") from exc
        released = True
        active = False
        return {"released_agent_ids": ids.copy(), "live_no_drain_authorized": False}

    def release_installed(confirmation):
        nonlocal active, released
        if not recover_existing or terminal_recorded is None or local_hybrid_agent_id is None:
            raise HoldPreparationBlocked("reviewed_installed_terminal_release_required")
        if type(confirmation) is not dict or confirmation.get("local_hybrid_agent_id") != local_hybrid_agent_id:
            raise HoldPreparationBlocked("installed_terminal_hybrid_identity_mismatch")
        digest = _validate_installed_confirmation(confirmation, scope, terminal_recorded)
        checkpoint()
        try:
            for agent in ids:
                exchange(agent, "release_installed", {"confirmation": confirmation})
        except (OSError, RuntimeError, ValueError) as exc:
            active = False
            raise HoldPreparationBlocked("partial_installed_release_requires_review") from exc
        released = True
        active = False
        return {"released_agent_ids": ids.copy(), "confirmation_sha256": digest,
                "live_no_drain_authorized": False}

    with ExitStack() as stack:
        try:
            # Open every required channel first. A missing endpoint must
            # not cause an avoidable partial preparation on other hosts.
            used_fds = set()
            for agent in ids:
                deadline()
                pair = stack.enter_context(session_openers[agent]())
                if (not isinstance(pair, tuple) or len(pair) != 2
                        or any(type(fd) is not int or fd < 0 for fd in pair)
                        or used_fds.intersection(pair)):
                    raise HoldPreparationBlocked("distributed_agent_channel_invalid")
                used_fds.update(pair)
                sessions[agent] = (*pair, None)
            for agent in ids:
                exchange(agent, initial_action)
            checkpoint()
            yield {
                **scope, "status": "all_expected_cooperating_agent_sessions_retained",
                "prepared_agent_ids": ids.copy(),
                "recovery_scope_only": recover_existing,
                "cooperating_local_scopes_retained": len(ids),
                "checkpoint": checkpoint, "record_terminal": record_terminal,
                "release_fixture": release_fixture,
                "release_installed": release_installed,
                "transport_authentication_independently_verified": False,
                "remote_agents_acked": False, "external_jobs_acked": False,
                "live_no_drain_authorized": False,
            }
            if not released:
                checkpoint()
                for agent in ids:
                    exchange(agent, "close")
        except (OSError, ValueError, RuntimeError) as exc:
            raise HoldPreparationBlocked("distributed_agent_coordination_blocked") from exc
        finally:
            active = False
