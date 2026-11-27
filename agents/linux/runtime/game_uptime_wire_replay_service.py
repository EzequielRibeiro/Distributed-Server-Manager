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
import re
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
    JOURNAL_DIR, _validate_paths, _root_pending, NONCE, SHA,
)
from game_uptime_maintenance_hold import HOLD_PATH, PENDING_PATH, observe
from game_uptime_transaction_binding import BINDING_PATH, binding_for_hold
import time

DASHBOARD_UNIT = "/system.slice/dsm-dashboard.service"
DASHBOARD_SCRIPT = "/opt/dsm/dashboard/server_part22.py"
REQUEST_MAX = 8192
PROTOCOL = "dsm928-root-negative-wire-writer-v1"
REQUIRED = frozenset({"protocol", "authenticated_agent_id", "receipt"})
INVENTORY_PATH = Path("/var/lib/capivara-dsm-928/no-drain-agent-inventory.json")
_AGENT_ID = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")
_INVENTORY_KEYS = {"kind", "schema_version", "transaction_id",
                   "release_sha256", "issued_at", "expires_at", "agent_ids"}


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


def read_inventory(*, path: Path = INVENTORY_PATH, trusted_uid: int = 0) -> dict:
    """Read operator-pinned inventory, never the submitting Agent's list."""
    path = Path(path)
    if path != INVENTORY_PATH:
        import tempfile
        if (not path.is_absolute()
                or Path(tempfile.gettempdir()).resolve() not in path.parents
                or trusted_uid != os.geteuid()):
            raise RootWriterBlocked("inventory_path_override")
    elif trusted_uid != 0:
        raise RootWriterBlocked("inventory_not_root_owned")
    try:
        parents = ((Path("/var"), Path("/var/lib"), path.parent)
                   if path == INVENTORY_PATH else (path.parent.parent, path.parent))
        for parent in parents:
            meta = parent.lstat()
            if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != trusted_uid
                    or meta.st_mode & 0o022):
                raise RootWriterBlocked("inventory_parent_untrusted")
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != trusted_uid
                or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= 16384):
            raise RootWriterBlocked("inventory_file_untrusted")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            actual = os.fstat(fd)
            def identity(meta):
                return (meta.st_dev, meta.st_ino, meta.st_size, meta.st_uid,
                        meta.st_mode, meta.st_nlink, meta.st_mtime_ns, meta.st_ctime_ns)
            if identity(actual) != identity(before):
                raise RootWriterBlocked("inventory_inode_changed")
            with os.fdopen(os.dup(fd), "rb") as stream:
                raw = stream.read(16385)
            if (len(raw) != actual.st_size
                    or identity(os.fstat(fd)) != identity(actual)
                    or identity(path.lstat()) != identity(actual)):
                raise RootWriterBlocked("inventory_read_changed")
        finally:
            os.close(fd)
        doc = json.loads(raw)
        if (not isinstance(doc, dict) or set(doc) != _INVENTORY_KEYS
                or raw != (json.dumps(doc, sort_keys=True, separators=(",", ":"))
                           + "\n").encode("ascii")):
            raise RootWriterBlocked("inventory_not_canonical")
        return doc
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        raise RootWriterBlocked("independent_agent_inventory_unavailable") from exc


def _inventory_scope(doc: dict, receipt: dict, agent: str) -> list[str]:
    if (not isinstance(doc, dict) or set(doc) != _INVENTORY_KEYS
            or doc.get("kind") != "DSM928OperatorAgentInventory"
            or type(doc.get("schema_version")) is not int
            or doc["schema_version"] != 1
            or any(doc.get(key) != receipt.get(key) for key in (
                "transaction_id", "release_sha256", "issued_at", "expires_at"))
            or type(doc.get("issued_at")) is not int
            or type(doc.get("expires_at")) is not int):
        raise RootWriterBlocked("inventory_transaction_mismatch")
    ids = doc.get("agent_ids")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 64
            or any(type(item) is not str or not _AGENT_ID.fullmatch(item)
                   for item in ids)
            or len(set(ids)) != len(ids) or agent not in ids):
        raise RootWriterBlocked("agent_not_in_independent_inventory")
    return ids


def inspect_persisted_receipts(*, journal_dir: Path = JOURNAL_DIR,
                               hold_path: Path = HOLD_PATH,
                               pending_path: Path = PENDING_PATH,
                               binding_path: Path = BINDING_PATH,
                               trusted_uid: int = 0, now: int | None = None,
                               fixture_only: bool = False,
                               expected_release_sha256: str | None = None) -> dict:
    """Reconstruct wire coverage after a restart; NEVER reconstruct an ACK.

    Only the independently pinned inventory determines the denominator.
    Historical records stay immutable; multiple nonces from the same Agent
    count once. A partial/unsafe record or changed snapshot blocks review.
    """
    directory, marker, pending, binding = map(
        Path, (journal_dir, hold_path, pending_path, binding_path))
    _validate_paths(directory, marker, pending, binding, trusted_uid, fixture_only)
    inventory_path = pending.parent / "no-drain-agent-inventory.json"
    when = int(time.time()) if now is None else now
    def scope():
        held = observe(path=marker, pending_path=pending, trusted_uid=trusted_uid, now=when)
        if held.get("reason") != "root_owned_maintenance_hold" or held.get("active") is not True:
            raise RootWriterBlocked("receipt_review_hold_unavailable")
        tx = held["transaction_id"]
        _root_pending(pending, trusted_uid, tx, held["issued_at"], held["expires_at"])
        pin = binding_for_hold(held, path=binding, trusted_uid=trusted_uid, now=when)
        if not pin or (expected_release_sha256 is not None
                       and pin.get("release_sha256") != expected_release_sha256):
            raise RootWriterBlocked("receipt_review_release_mismatch")
        inv = read_inventory(path=inventory_path, trusted_uid=trusted_uid)
        ids = inv.get("agent_ids")
        if not isinstance(ids, list) or not ids:
            raise RootWriterBlocked("receipt_review_inventory_missing")
        expected = _inventory_scope(inv, {**held, "release_sha256": pin["release_sha256"]}, ids[0])
        return tx, pin["release_sha256"], held["expires_at"], tuple(sorted(expected))
    def identity(meta):
        return (meta.st_dev, meta.st_ino, meta.st_uid, meta.st_mode,
                meta.st_nlink, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)
    original = scope()
    tx, sha, expires, expected = original
    directory_before = identity(directory.lstat())
    seen, sampled = set(), {}
    for index, entry in enumerate(directory.iterdir()):
        if index >= 4096 or not NONCE.fullmatch(entry.stem) or entry.suffix != ".json":
            raise RootWriterBlocked("receipt_review_unexpected_journal_entry")
        before = entry.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != trusted_uid
                or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= 2048):
            raise RootWriterBlocked("receipt_review_untrusted_record")
        fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            raw = os.read(fd, 2049)
            if (len(raw) != before.st_size or identity(os.fstat(fd)) != identity(before)
                    or identity(entry.lstat()) != identity(before)):
                raise RootWriterBlocked("receipt_review_record_changed")
        finally:
            os.close(fd)
        doc = json.loads(raw)
        agent = doc.get("authenticated_agent_id_claim_from_caller") if isinstance(doc, dict) else None
        if (not isinstance(doc, dict) or type(agent) is not str
                or not _AGENT_ID.fullmatch(agent)
                or type(doc.get("transaction_id")) is not str
                or not NONCE.fullmatch(doc["transaction_id"])
                or type(doc.get("release_sha256")) is not str
                or not SHA.fullmatch(doc["release_sha256"])):
            raise RootWriterBlocked("receipt_review_record_identity_invalid")
        canonical = {
            "kind": "DSM928CredentialedNegativeWireReceiptJournal", "schema_version": 1,
            "authenticated_agent_id_claim_from_caller": agent,
            "transaction_id": doc["transaction_id"], "release_sha256": doc["release_sha256"],
            "request_id": entry.stem, "scope": "negative_wire_receipt_only_not_quiescence",
            "wire_receipt_received": True, "transport_authentication_independently_verified": False,
            "remote_agent_quiescence_acked": False, "external_jobs_acked": False,
            "live_no_drain_authorized": False,
        }
        if raw != (json.dumps(canonical, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"):
            raise RootWriterBlocked("receipt_review_record_contract_invalid")
        sampled[entry] = identity(before)
        if doc["transaction_id"] != tx:
            continue
        if doc["release_sha256"] != sha or agent not in expected:
            raise RootWriterBlocked("receipt_review_record_scope_mismatch")
        seen.add(agent)
    if (scope() != original or identity(directory.lstat()) != directory_before
            or any(identity(path.lstat()) != meta for path, meta in sampled.items())
            or (now is None and int(time.time()) >= expires)):
        raise RootWriterBlocked("receipt_review_snapshot_changed")
    return {
        "status": "persisted_negative_receipts_observed",
        "expected_agent_count": len(expected), "observed_agent_count": len(seen),
        "missing_agent_ids": sorted(set(expected) - seen),
        "wire_receipt_inventory_complete": set(expected) == seen,
        "remote_agents_acked": False, "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }


def commit_request(raw: bytes, *, record_fn: Callable = record_authenticated_negative_receipt,
                   inventory_fn: Callable = read_inventory) -> dict:
    """Consume a negative v2 request, with no positive ACK code path.

    The record function is injectable only inside local regression tests; the
    installed daemon calls the root-only journal implementation directly.
    """
    request = decode_request(raw)
    agent = request["authenticated_agent_id"]
    receipt = request["receipt"]
    expected_agents = _inventory_scope(inventory_fn(), receipt, agent)
    result = record_fn(
        authenticated_agent_id=agent,
        expected_agent_ids=expected_agents,
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
