#!/usr/bin/env python3
"""#928 persistent replay witness for credentialed NEGATIVE Agent receipts.

A privileged coordinator may record a v2 receipt that has already passed the
Controller's credentialed HTTP dispatcher. This function does NOT authenticate
the transport, enroll hosts or attest quiescence. No live no-drain authorization
or updater integration is performed. The receipt journal is append-only:
O_EXCL+fsync rejects a reused nonce even after the coordinator restarts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any, Mapping, Sequence

from game_uptime_maintenance_hold import HOLD_PATH, PENDING_PATH, observe
from game_uptime_transaction_binding import (
    BINDING_PATH, binding_for_hold, ReleaseBindingBlocked,
)

JOURNAL_DIR = Path("/var/lib/capivara-dsm-928/no-drain-wire-receipts")
NONCE = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
AGENT = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")
V2 = {"protocol": "dsm928-fence-evidence-release-bound-readonly-v2",
      "schema": "2"}
REQUIRED = frozenset({
    "kind", "schema_version", "agent_id", "request_id", "transaction_id",
    "issued_at", "expires_at", "contract", "status", "scope",
    "agent_workers_fenced", "remote_agent_quiescence_acked",
    "live_no_drain_authorized", "release_sha256",
})
_PENDING_KEYS = frozenset({
    "kind", "schema_version", "transaction_id", "issued_at", "expires_at",
    "state", "live_no_drain_authorized",
})


class DurableWireReplayBlocked(RuntimeError):
    pass


def _directory(path: Path, uid: int, *, private: bool = False) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise DurableWireReplayBlocked("wire_journal_directory_missing") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or (private and info.st_mode & (stat.S_IRWXG | stat.S_IRWXO))):
        raise DurableWireReplayBlocked("wire_journal_directory_untrusted")


def _validate_paths(journal: Path, hold: Path, pending: Path,
                    binding: Path, uid: int, fixture: bool) -> None:
    if os.geteuid() != uid:
        raise DurableWireReplayBlocked("privileged_writer_uid_mismatch")
    if not fixture:
        if (uid != 0 or journal != JOURNAL_DIR or hold != HOLD_PATH
                or pending != PENDING_PATH or binding != BINDING_PATH):
            raise DurableWireReplayBlocked("installed_paths_and_root_required")
        for folder in (Path("/var"), Path("/var/lib"), journal.parent):
            _directory(folder, uid)
    else:
        temp = Path(tempfile.gettempdir()).resolve(strict=True)
        root = journal.parent.parent
        if (not all(p.is_absolute() for p in (
                journal, hold, pending, binding))
                or temp not in root.parents
                or any(root not in p.parents for p in (
                    hold, pending, binding))):
            raise DurableWireReplayBlocked("disposable_paths_escape_workspace")
        _directory(root, uid)
        _directory(journal.parent, uid)
        for folder in {hold.parent, pending.parent, binding.parent}:
            _directory(folder, uid)
    _directory(journal, uid, private=True)


def _root_pending(path: Path, uid: int, tx: str,
                  issued: int, expires: int) -> None:
    try:
        old = path.lstat()
        if (not stat.S_ISREG(old.st_mode) or old.st_uid != uid
                or old.st_nlink != 1 or
                stat.S_IMODE(old.st_mode) != 0o600
                or old.st_size <= 0 or old.st_size > 2048):
            raise DurableWireReplayBlocked("pending_journal_untrusted")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            current = os.fstat(fd)
            if (current.st_ino, current.st_dev, current.st_size,
                    current.st_mtime_ns) != (
                    old.st_ino, old.st_dev, old.st_size, old.st_mtime_ns):
                raise DurableWireReplayBlocked("pending_journal_changed")
            data = os.read(fd, 2049)
        finally:
            os.close(fd)
        doc = json.loads(data)
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        raise DurableWireReplayBlocked("pending_journal_invalid") from exc
    if (not isinstance(doc, dict) or set(doc) != _PENDING_KEYS
            or doc.get("kind") != "CapivaraDSMNoDrainPendingJournal"
            or type(doc.get("schema_version")) is not int
            or doc["schema_version"] != 1
            or doc.get("state") != "prepared_requires_distributed_fence"
            or doc.get("transaction_id") != tx
            or type(doc.get("issued_at")) is not int
            or doc["issued_at"] != issued
            or type(doc.get("expires_at")) is not int
            or doc["expires_at"] != expires
            or doc.get("live_no_drain_authorized") is not False):
        raise DurableWireReplayBlocked("pending_journal_identity_mismatch")


def _receipt(receipt: Mapping[str, Any], agent: str, tx: str,
             sha: str, issued: int, expires: int, now: int) -> str:
    if (not isinstance(receipt, Mapping) or set(receipt) != REQUIRED
            or receipt.get("kind") != "CapivaraNoDrainFenceEvidenceReceipt"
            or type(receipt.get("schema_version")) is not int
            or receipt["schema_version"] != 1
            or receipt.get("agent_id") != agent
            or receipt.get("transaction_id") != tx
            or receipt.get("release_sha256") != sha
            or receipt.get("contract") != V2
            or receipt.get("status") != "authenticated_evidence_received_unfenced"
            or receipt.get("scope") != "authenticated_heartbeat_wire_only"
            or receipt.get("agent_workers_fenced") is not False
            or receipt.get("remote_agent_quiescence_acked") is not False
            or receipt.get("live_no_drain_authorized") is not False
            or type(receipt.get("issued_at")) is not int
            or receipt["issued_at"] != issued
            or type(receipt.get("expires_at")) is not int
            or receipt["expires_at"] != expires
            or not issued <= now < expires):
        raise DurableWireReplayBlocked("receipt_not_valid_negative_v2")
    nonce = receipt.get("request_id")
    if type(nonce) is not str or not NONCE.fullmatch(nonce):
        raise DurableWireReplayBlocked("receipt_nonce_invalid")
    return nonce


def record_authenticated_negative_receipt(
    *, authenticated_agent_id: str, expected_agent_ids: Sequence[str],
    receipt: Mapping[str, Any], expected_transaction_id: str,
    expected_release_sha256: str,
    journal_dir: Path = JOURNAL_DIR, hold_path: Path = HOLD_PATH,
    pending_path: Path = PENDING_PATH, binding_path: Path = BINDING_PATH,
    trusted_uid: int = 0, now: int | None = None,
    fixture_only: bool = False,
) -> dict[str, Any]:
    """Consume one v2 negative receipt without granting any ACK.

    The caller MUST have verified the Agent's credential with the real
    Controller transport and obtained the expected Agent inventory from
    the authoritative Controller database. This function cannot attest
    either. It only verifies local root-owned transaction evidence and
    enforces durable nonce uniqueness for those submitted receipts.
    """
    when = int(time.time()) if now is None else now
    tx, sha, agent = expected_transaction_id, expected_release_sha256, authenticated_agent_id
    if (type(when) is not int or type(tx) is not str
            or not NONCE.fullmatch(tx) or type(sha) is not str
            or not SHA.fullmatch(sha) or type(agent) is not str
            or not AGENT.fullmatch(agent)
            or not isinstance(expected_agent_ids, (list, tuple))
            or not 1 <= len(expected_agent_ids) <= 64
            or any(type(x) is not str or not AGENT.fullmatch(x)
                   for x in expected_agent_ids)
            or len(expected_agent_ids) != len(set(expected_agent_ids))
            or agent not in expected_agent_ids):
        raise DurableWireReplayBlocked("invalid_expected_agent_transaction_scope")

    directory, hold_path, pending_path, binding_path = (
        Path(journal_dir), Path(hold_path), Path(pending_path), Path(binding_path))
    _validate_paths(directory, hold_path, pending_path,
                    binding_path, trusted_uid, fixture_only)
    observation = observe(
        path=hold_path, trusted_uid=trusted_uid,
        pending_path=pending_path, now=when)
    if (observation.get("active") is not True
            or observation.get("reason") != "root_owned_maintenance_hold"
            or observation.get("transaction_id") != tx):
        raise DurableWireReplayBlocked("root_hold_unavailable_or_wrong_transaction")
    issued, expires = observation["issued_at"], observation["expires_at"]
    _root_pending(pending_path, trusted_uid, tx, issued, expires)
    try:
        pin = binding_for_hold(
            observation, path=binding_path, trusted_uid=trusted_uid, now=when)
    except ReleaseBindingBlocked as exc:
        raise DurableWireReplayBlocked("root_release_binding_invalid") from exc
    if pin is None or pin.get("release_sha256") != sha:
        raise DurableWireReplayBlocked("independent_release_pin_mismatch")
    nonce = _receipt(receipt, agent, tx, sha, issued, expires, when)
    record = {
        "kind": "DSM928CredentialedNegativeWireReceiptJournal",
        "schema_version": 1,
        "authenticated_agent_id_claim_from_caller": agent,
        "transaction_id": tx,
        "release_sha256": sha,
        "request_id": nonce,
        "scope": "negative_wire_receipt_only_not_quiescence",
        "wire_receipt_received": True,
        "transport_authentication_independently_verified": False,
        "remote_agent_quiescence_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
    target = directory / (nonce + ".json")
    data = (json.dumps(record, sort_keys=True, separators=(",", ":"))
            + "\n").encode("ascii")
    flags = (os.O_CREAT | os.O_EXCL | os.O_WRONLY
             | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise DurableWireReplayBlocked("replayed_or_existing_wire_nonce") from exc
    try:
        if os.fstat(fd).st_uid != trusted_uid:
            raise DurableWireReplayBlocked("unexpected_wire_journal_owner")
        rest = memoryview(data)
        while rest:
            count = os.write(fd, rest)
            if count <= 0:
                raise OSError("short negative receipt journal write")
            rest = rest[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return record
