#!/usr/bin/env python3
"""DSM #928: root-only, socket-activated negative-receipt journal writer.

The systemd socket has mode 0600, owned by the DSM Dashboard user.
Every accepted connection MUST come from that user's live
dsm-dashboard.service process (SO_PEERCRED + /proc/cgroup/cmdline).
The writer checks a separate root-owned hold, persistent pending journal
and release pin, and can only append a NEGATIVE v2 wire receipt. It cannot
authorize, renew or clear a maintenance transaction, or invoke update.sh.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import socket
import struct
import sys
import stat
from typing import Any, Callable

# Isolated Python (-I -S) does not put its script directory on sys.path.
# ONLY the installed, root-owned executable may add the trusted immutable
# module directory, before importing any privileged implementation modules.
TRUSTED_LIBEXEC = Path("/usr/local/libexec/capivara-dsm-928")
TRUSTED_MODULES = (
    "game_uptime_wire_replay_service.py",
    "game_uptime_durable_wire_replay.py",
    "game_uptime_maintenance_hold.py",
    "game_uptime_transaction_binding.py",
)

def _trusted_root_snapshot() -> bool:
    try:
        if (Path(__file__) !=
                TRUSTED_LIBEXEC / "game_uptime_wire_replay_service.py"):
            return False
        for folder in (Path("/usr"), Path("/usr/local"),
                       Path("/usr/local/libexec"), TRUSTED_LIBEXEC):
            meta = folder.lstat()
            if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0
                    or meta.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                return False
        for file in TRUSTED_MODULES:
            meta = (TRUSTED_LIBEXEC / file).lstat()
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0
                    or meta.st_nlink != 1
                    or meta.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                return False
        return True
    except OSError:
        return False

if __name__ == "__main__":
    if not _trusted_root_snapshot():
        raise SystemExit(2)
    sys.path.insert(0, str(TRUSTED_LIBEXEC))

from game_uptime_durable_wire_replay import (
    DurableWireReplayBlocked, record_authenticated_negative_receipt,
)

DASHBOARD_UNIT = "/system.slice/dsm-dashboard.service"
DASHBOARD_SCRIPT = "/opt/dsm/dashboard/server_part22.py"
REQUEST_MAX = 8192
PROTOCOL = "dsm928-root-negative-wire-writer-v1"
REQUIRED = frozenset({"protocol", "authenticated_agent_id", "receipt"})


class RootWriterBlocked(RuntimeError):
    pass


def peer_is_dashboard(*, pid: int, uid: int, expected_uid: int,
                      proc_root: Path = Path("/proc")) -> bool:
    """Validate kernel peer credentials against the installed unit.

    This is an identity check, NOT independent Agent authentication.
    """
    if (type(pid) is not int or pid <= 1 or type(uid) is not int
            or uid < 1 or uid != expected_uid):
        return False
    base = proc_root / str(pid)
    try:
        cgroup = (base / "cgroup").read_text(encoding="ascii")
        memberships = [line.split(":", 2)[2] for line in cgroup.splitlines()
                       if line.startswith("0::")]
        argv_raw = (base / "cmdline").read_bytes()
        args = argv_raw[:-1].split(b"\0") if argv_raw.endswith(b"\0") else []
        if (memberships != [DASHBOARD_UNIT] or len(args) < 2
                or Path(os.fsdecode(args[0])).name not in (
                    "python3", "python3.12", "python3.13", "python3.14")
                or os.fsdecode(args[1]) != DASHBOARD_SCRIPT):
            return False
        raw_status = (base / "status").read_text(encoding="ascii")
        match = [line.split() for line in raw_status.splitlines()
                 if line.startswith("Uid:")]
        if len(match) != 1 or len(match[0]) != 5:
            return False
        # Effective UID is column 2 after the Uid: label.
        return int(match[0][2]) == expected_uid
    except (OSError, ValueError, UnicodeError, IndexError):
        return False


def decode_request(raw: bytes) -> dict[str, Any]:
    if (not isinstance(raw, bytes) or len(raw) <= 1
            or len(raw) > REQUEST_MAX or not raw.endswith(b"\n")
            or b"\n" in raw[:-1]):
        raise RootWriterBlocked("invalid_request_framing")
    def no_duplicates(pairs):
        doc = {}
        for key, value in pairs:
            if key in doc:
                raise RootWriterBlocked("duplicate_request_key")
            doc[key] = value
        return doc
    try:
        req = json.loads(raw, object_pairs_hook=no_duplicates)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise RootWriterBlocked("invalid_request_json") from exc
    if (not isinstance(req, dict) or set(req) != REQUIRED
            or req.get("protocol") != PROTOCOL
            or type(req.get("authenticated_agent_id")) is not str
            or not isinstance(req.get("receipt"), dict)):
        raise RootWriterBlocked("invalid_request_contract")
    return req


def commit_request(raw: bytes, *, record_fn: Callable = record_authenticated_negative_receipt) -> dict:
    """Consume a negative v2 request, with no positive ACK code path.

    The record function is injectable only inside local regression tests; the
    installed daemon calls the root-only journal implementation directly.
    """
    request = decode_request(raw)
    agent = request["authenticated_agent_id"]
    receipt = request["receipt"]
    result = record_fn(
        authenticated_agent_id=agent,
        expected_agent_ids=[agent],
        receipt=receipt,
        expected_transaction_id=receipt.get("transaction_id"),
        expected_release_sha256=receipt.get("release_sha256"),
    )
    if (not isinstance(result, dict)
            or result.get("wire_receipt_received") is not True
            or result.get("remote_agent_quiescence_acked") is not False
            or result.get("live_no_drain_authorized") is not False):
        raise RootWriterBlocked("untrusted_durable_journal_result")
    return {
        "status": "negative_v2_receipt_durably_recorded",
        "transaction_id": receipt["transaction_id"],
        "release_sha256": receipt["release_sha256"],
        "request_id": receipt["request_id"],
        "remote_agent_quiescence_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }


def serve_stdin(*, expected_dashboard_user: str) -> int:
    """One accepted AF_UNIX connection per systemd socket-activated unit."""
    if os.geteuid() != 0 or not expected_dashboard_user:
        return 2
    try:
        expected_uid = pwd.getpwnam(expected_dashboard_user).pw_uid
        if expected_uid == 0:
            return 2
        accepted = socket.socket(fileno=os.dup(0))
        try:
            if accepted.family != socket.AF_UNIX or accepted.type & 0xf != socket.SOCK_STREAM:
                return 2
            peer_raw = accepted.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, _gid = struct.unpack("3i", peer_raw)
            if not peer_is_dashboard(
                    pid=pid, uid=uid, expected_uid=expected_uid):
                return 2
            accepted.settimeout(4.0)
            data = bytearray()
            while b"\n" not in data and len(data) <= REQUEST_MAX:
                packet = accepted.recv(min(4096, REQUEST_MAX+1-len(data)))
                if not packet:
                    break
                data.extend(packet)
            try:
                response = commit_request(bytes(data))
            except (RootWriterBlocked, DurableWireReplayBlocked,
                    OSError, ValueError, TypeError):
                response = {"status": "blocked",
                            "remote_agent_quiescence_acked": False,
                            "live_no_drain_authorized": False}
            accepted.sendall((json.dumps(response, sort_keys=True,
                                          separators=(",", ":"))+"\n").encode("ascii"))
            return 0 if response["status"] == "negative_v2_receipt_durably_recorded" else 2
        finally:
            accepted.close()
    except (OSError, LookupError, ValueError, TypeError, socket.timeout):
        return 2


if __name__ == "__main__":
    if (len(sys.argv) != 3 or sys.argv[1] != "--expected-dashboard-user"):
        raise SystemExit(2)
    raise SystemExit(serve_stdin(expected_dashboard_user=sys.argv[2]))
