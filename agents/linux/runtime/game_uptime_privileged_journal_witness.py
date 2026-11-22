#!/usr/bin/env python3
"""DSM #928: local root journal/lease AND privileged-helper lock witness.

A read-only, scoped negative observation: NO remote ACK, updater hook, lease
renewal, journal cleanup, or permission for live no-drain. Lock EX only means
that five *opted-in* parent helper entrypoints on this host are not inside
their protected run() at that instant. It says nothing about detached jobs
or whether every deployed helper has the opt-in feature enabled.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Iterator, Any

from game_uptime_maintenance_hold import HOLD_PATH, PENDING_PATH, observe
from game_uptime_privileged_flock import (
    LOCK_PATH, PrivilegedHelperFenceUnavailable,
    exclusive_privileged_helper_lock,
)

_TRANSACTION = re.compile(r"[0-9a-f]{32}\Z")
_PENDING_KEYS = frozenset({
    "kind", "schema_version", "transaction_id", "issued_at", "expires_at",
    "state", "live_no_drain_authorized",
})


class PrivilegedJournalWitnessBlocked(RuntimeError):
    """Invalid/busy/stale local evidence requires operator investigation."""


def _read_pending(path: Path, uid: int) -> dict[str, Any]:
    """Read root-owned journal without altering, following or replacing it."""
    for parent in (path.parent.parent, path.parent):
        try:
            item = parent.lstat()
        except OSError as exc:
            raise PrivilegedJournalWitnessBlocked("pending_parent_unavailable") from exc
        if (not stat.S_ISDIR(item.st_mode) or item.st_uid != uid
                or item.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise PrivilegedJournalWitnessBlocked("pending_parent_untrusted")
    try:
        before = path.lstat()
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        raise PrivilegedJournalWitnessBlocked("pending_missing_or_unreadable") from exc
    try:
        current = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
                or current.st_uid != uid or current.st_nlink != 1
                or stat.S_IMODE(current.st_mode) != 0o600
                or not (0 < current.st_size <= 2048)):
            raise PrivilegedJournalWitnessBlocked("pending_inode_untrusted")
        raw = os.read(fd, 2049)
        if len(raw) != current.st_size:
            raise PrivilegedJournalWitnessBlocked("pending_size_changed")
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PrivilegedJournalWitnessBlocked("pending_json_invalid") from exc
    if (not isinstance(payload, dict)
            or set(payload) != _PENDING_KEYS
            or payload.get("kind") != "CapivaraDSMNoDrainPendingJournal"
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
            or payload.get("state") != "prepared_requires_distributed_fence"
            or payload.get("live_no_drain_authorized") is not False
            or type(payload.get("transaction_id")) is not str
            or not _TRANSACTION.fullmatch(payload["transaction_id"])
            or type(payload.get("issued_at")) is not int
            or type(payload.get("expires_at")) is not int):
        raise PrivilegedJournalWitnessBlocked("pending_contract_invalid")
    return payload


def _verify_snapshot(*, expected_transaction_id: str, hold_path: Path,
                     journal_path: Path, trusted_uid: int, now: int | None
                     ) -> tuple[str, int, int]:
    current = int(time.time()) if now is None else now
    snapshot = observe(path=hold_path, pending_path=journal_path,
                       trusted_uid=trusted_uid, now=current)
    pending = _read_pending(journal_path, trusted_uid)
    tx, issued, expires = (
        pending["transaction_id"], pending["issued_at"], pending["expires_at"])
    if (snapshot.get("active") is not True
            or snapshot.get("reason") != "root_owned_maintenance_hold"
            or tx != expected_transaction_id
            or any(snapshot.get(key) != pending[key] for key in (
                "transaction_id", "issued_at", "expires_at"))
            or not (0 < issued <= current + 30)
            or not (issued <= current < expires <= issued + 900)):
        raise PrivilegedJournalWitnessBlocked("root_hold_pending_lease_mismatch")
    return tx, issued, expires


@contextmanager
def local_privileged_journal_witness(
    *, expected_transaction_id: str,
    hold_path: Path = HOLD_PATH, journal_path: Path = PENDING_PATH,
    lock_path: Path = LOCK_PATH, trusted_uid: int = 0,
    now: int | None = None,
) -> Iterator[dict[str, object]]:
    """Take EX on one host, then verify root journal+hold twice, read-only.

    Installed fixed paths are root-only; override paths are ONLY for isolated
    fixtures. Never infer quiescence of other processes or remote Agents.
    """
    hold_path, journal_path, lock_path = (
        Path(hold_path), Path(journal_path), Path(lock_path))
    if (not isinstance(expected_transaction_id, str)
            or not _TRANSACTION.fullmatch(expected_transaction_id)
            or type(trusted_uid) is not int
            or os.geteuid() != trusted_uid
            or any(not path.is_absolute() for path in (
                hold_path, journal_path, lock_path))
            or len({hold_path, journal_path, lock_path}) != 3
            or (os.geteuid() != 0 and any((
                hold_path == HOLD_PATH, journal_path == PENDING_PATH,
                lock_path == LOCK_PATH)))):
        raise PrivilegedJournalWitnessBlocked("root_only_local_witness_required")
    try:
        with exclusive_privileged_helper_lock(
                path=lock_path, trusted_uid=trusted_uid):
            initial = _verify_snapshot(
                expected_transaction_id=expected_transaction_id,
                hold_path=hold_path, journal_path=journal_path,
                trusted_uid=trusted_uid, now=now)
            yield {
                "status": "root_hold_and_five_helper_parents_observed_local_only",
                "scope": "five_opted_in_privileged_helper_parent_runs_on_this_host_only",
                "transaction_id": initial[0],
                "journal_lease_matched_locally": True,
                "all_helper_processes_opted_in_verified": False,
                "privileged_helper_acked": False,
                "controller_http_acked": False,
                "external_jobs_acked": False,
                "remote_agents_acked": False,
                "live_no_drain_authorized": False,
            }
            if _verify_snapshot(
                expected_transaction_id=expected_transaction_id,
                hold_path=hold_path, journal_path=journal_path,
                trusted_uid=trusted_uid, now=now) != initial:
                raise PrivilegedJournalWitnessBlocked(
                    "root_hold_changed_during_local_witness")
    except PrivilegedHelperFenceUnavailable as exc:
        raise PrivilegedJournalWitnessBlocked(
            "privileged_helper_lock_not_exclusively_available") from exc



@contextmanager
def local_privileged_and_finalization_journal_witness(
    *, expected_transaction_id: str,
    hold_path: Path = HOLD_PATH, journal_path: Path = PENDING_PATH,
    privileged_lock_path: Path = LOCK_PATH,
    finalization_lock_path: Path | None = None,
    trusted_uid: int = 0, finalization_group_gid: int | None = None,
    now: int | None = None,
) -> Iterator[dict[str, object]]:
    """Witness TWO local in-flight lock families under the SAME journal lease.

    Retain the finalization EX while the existing privileged-helper witness
    acquires EX, checks the root-owned hold/pending journal, yields, and
    rechecks the journal before exit. Neither lock is created or repaired.
    A free lock cannot attest that every process enabled its opt-in flag.
    """
    from game_uptime_finalization_flock import (
        LOCK_PATH as FINALIZATION_LOCK_PATH,
        FinalizationFenceUnavailable, exclusive_finalization_lock,
    )

    child_lock = Path(
        FINALIZATION_LOCK_PATH if finalization_lock_path is None
        else finalization_lock_path
    )
    privileged = Path(privileged_lock_path)
    marker, pending = Path(hold_path), Path(journal_path)
    if (not child_lock.is_absolute()
            or child_lock in (privileged, marker, pending)
            or type(trusted_uid) is not int
            or (child_lock == FINALIZATION_LOCK_PATH
                and finalization_group_gid is not None)
            or (child_lock != FINALIZATION_LOCK_PATH
                and type(finalization_group_gid) is not int)):
        raise PrivilegedJournalWitnessBlocked(
            "finalization_witness_paths_or_identity_invalid"
        )

    # Installed lock identities are fixed inside the finalization module.
    # Test-only paths carry explicit UID/GID and do not bypass its checks.
    identity = (
        {} if child_lock == FINALIZATION_LOCK_PATH else
        {"trusted_uid": trusted_uid, "group_gid": finalization_group_gid}
    )
    try:
        with exclusive_finalization_lock(path=child_lock, **identity):
            with local_privileged_journal_witness(
                expected_transaction_id=expected_transaction_id,
                hold_path=marker,
                journal_path=pending,
                lock_path=privileged,
                trusted_uid=trusted_uid,
                now=now,
            ) as helper:
                yield {
                    **helper,
                    "status": "root_journal_two_lock_families_observed_local_only",
                    "scope": "cooperating_helper_parents_and_finalization_children_one_host_only",
                    "finalization_child_lock_exclusive": True,
                    "all_finalization_children_opted_in_verified": False,
                    "external_jobs_acked": False,
                    "remote_agents_acked": False,
                    "live_no_drain_authorized": False,
                }
    except FinalizationFenceUnavailable as exc:
        raise PrivilegedJournalWitnessBlocked(
            "finalization_child_lock_not_exclusively_available"
        ) from exc
