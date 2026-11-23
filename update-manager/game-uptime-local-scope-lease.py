#!/usr/bin/env python3
"""#928: retain Controller/Worker kernel fences through a bounded local scope.

This is a real flock-based LOCAL primitive (not a synthetic ACK), but it
covers ONLY 3 Controller Agent HTTP routes and 9 registered Worker cycles.
It cannot attest other APIs, Agents on other hosts, external jobs, game PIDs
or a release's authenticity, and NEVER grants a live no-drain update.

The installed path requires an existing operator-owned hold. Only the marked
disposable fixture can prepare a fresh durable hold under the retained locks.
Never removes evidence, changes systemd units or calls update.sh.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
from importlib.machinery import SourceFileLoader
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Iterator

CONTROLLER_LOCK = Path("/run/capivara-dsm/controller-agent-http.lock")
WORKER_LOCK_DIR = Path("/run/capivara-dsm/worker-operations")
HOLD_PATH = Path("/run/capivara-dsm/no-drain-maintenance.json")
PENDING_PATH = Path("/var/lib/capivara-dsm-928/no-drain-pending.json")
WORKERS = (
    "automation_worker", "content_update_worker",
    "content_upload_retention_worker", "database_intelligence_worker",
    "hybrid_agent_worker", "hybrid_customer_workspace_worker",
    "maintenance_worker", "observability_retention_worker",
    "scheduler_worker",
)
_TX = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OWNER_MARKER = b"DSM928_DISPOSABLE_FIXTURE_V1\n"


class LocalScopeLeaseBlocked(RuntimeError):
    pass


def _hold_module():
    path = (Path(__file__).resolve().parents[1]
            / "agents/linux/runtime/game_uptime_maintenance_hold.py")
    loader = SourceFileLoader("dsm928_scope_lease_hold", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _safe_directory(path: Path, *, owner: int) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise LocalScopeLeaseBlocked("untrusted_local_fence_directory")


def _directory_chain(path: Path, *, fixture_root: Path | None,
                     owner: int) -> None:
    if fixture_root is None:
        # Locks/ephemeral hold live under /run; crash-recovery sentinel
        # lives on persistent /var/lib. Both must have root-owned parents.
        anchor = next((base for base in (Path("/run"), Path("/var/lib"))
                       if base == path or base in path.parents), None)
        if anchor is None:
            raise LocalScopeLeaseBlocked("lock_outside_root_owned_state")
        if anchor == Path("/var/lib"):
            _safe_directory(Path("/var"), owner=0)
        _safe_directory(anchor, owner=0)
        current = anchor
        parts = path.relative_to(current).parts
    else:
        try:
            parts = path.relative_to(fixture_root).parts
        except ValueError as exc:
            raise LocalScopeLeaseBlocked("lock_outside_disposable_root") from exc
        current = fixture_root
        _safe_directory(current, owner=owner)
    for part in parts:
        current = current / part
        _safe_directory(current, owner=owner)


def _open_existing_lock(path: Path, *, owner_uid: int) -> int:
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner_uid
            or before.st_nlink != 1 or before.st_size != 0
            or stat.S_IMODE(before.st_mode) != 0o600):
        raise LocalScopeLeaseBlocked("untrusted_preprovisioned_lock")
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK
                 | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0))
    try:
        after = os.fstat(fd)
        if (not stat.S_ISREG(after.st_mode) or
                (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                or after.st_uid != owner_uid or after.st_nlink != 1
                or after.st_size != 0 or
                stat.S_IMODE(after.st_mode) != 0o600):
            raise LocalScopeLeaseBlocked("preprovisioned_lock_replaced")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _trusted_fixture_root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise LocalScopeLeaseBlocked("disposable_fixture_root_missing")
    real = root.resolve(strict=True)
    tmp = Path(tempfile.gettempdir()).resolve(strict=True)
    if real == tmp or tmp not in real.parents:
        raise LocalScopeLeaseBlocked("not_a_disposable_tmp_fixture")
    _safe_directory(real, owner=os.geteuid())
    # /run may be 0755, but the disposable workspace must be private.
    if real.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise LocalScopeLeaseBlocked("disposable_root_not_private")
    marker = real / "fixture-owner"
    if (marker.is_symlink() or not marker.is_file() or
            marker.stat().st_uid != os.geteuid()
            or marker.read_bytes() != _OWNER_MARKER):
        raise LocalScopeLeaseBlocked("missing_disposable_fixture_marker")
    return real


def _check_hold(module, path: Path, pending: Path, *, tx: str,
                owner: int) -> None:
    # A pending journal means crash recovery has precedence, even when a
    # perfectly formatted ephemeral hold is still present.
    if module._pending_recovery_reason(pending, owner) is not None:
        raise LocalScopeLeaseBlocked("persistent_recovery_pending")
    observed = module.observe(path=path, trusted_uid=owner,
                              pending_path=pending)
    if (observed.get("active") is not True
            or observed.get("reason") != "root_owned_maintenance_hold"
            or observed.get("transaction_id") != tx):
        raise LocalScopeLeaseBlocked("missing_or_mismatched_maintenance_hold")


def _require_absent(*paths: Path) -> None:
    for path in paths:
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        raise LocalScopeLeaseBlocked("persistent_recovery_pending")


def _evidence_identity(path: Path) -> tuple:
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _fresh_fixture_preparation(hold, hold_path: Path, pending_path: Path,
                               *, tx: str, sha: str, owner: int):
    """Create once, under retained locks; never accept a prior journal."""
    binding_path = pending_path.parent / "no-drain-release-binding.json"
    _require_absent(hold_path, pending_path, binding_path)
    # These imports are reached ONLY in an explicitly marked private /tmp
    # fixture; no installed root service or updater calls this branch.
    runtime = str(Path(__file__).resolve().parents[1] / "agents/linux/runtime")
    sys.path.insert(0, runtime)
    try:
        from game_uptime_hold_coordinator import prepare_root_only
        from game_uptime_transaction_binding import binding_for_hold
        from game_uptime_durable_wire_replay import _root_pending
    finally:
        sys.path.remove(runtime)
    try:
        prepared = prepare_root_only(
            transaction_id=tx, release_sha256=sha, trusted_uid=owner,
            journal_path=pending_path, hold_path=hold_path,
            binding_path=binding_path)
        if (prepared.get("release_identity_bound_locally") is not True
                or prepared.get("live_no_drain_authorized") is not False):
            raise LocalScopeLeaseBlocked("fresh_preparation_invalid")
        paths = (hold_path, pending_path, binding_path)
        identities = tuple(_evidence_identity(path) for path in paths)

        def checkpoint():
            observed = hold.observe(path=hold_path, trusted_uid=owner,
                                    pending_path=pending_path)
            if (observed.get("active") is not True
                    or observed.get("reason") != "root_owned_maintenance_hold"
                    or observed.get("transaction_id") != tx):
                raise LocalScopeLeaseBlocked("fresh_hold_invalid")
            _root_pending(pending_path, owner, tx,
                          observed["issued_at"], observed["expires_at"])
            pin = binding_for_hold(observed, path=binding_path, trusted_uid=owner)
            if (pin is None or pin.get("release_sha256") != sha
                    or tuple(_evidence_identity(path) for path in paths) != identities):
                raise LocalScopeLeaseBlocked("fresh_transaction_evidence_changed")
        checkpoint()
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalScopeLeaseBlocked("fresh_transaction_preparation_blocked") from exc
    return checkpoint


@contextmanager
def retain_local_scopes(*, transaction_id: str, release_sha256: str,
                        expected_controller_uid: int,
                        expected_worker_uid: int,
                        controller_lock: Path = CONTROLLER_LOCK,
                        worker_lock_dir: Path = WORKER_LOCK_DIR,
                        hold_path: Path = HOLD_PATH,
                        pending_path: Path = PENDING_PATH,
                        fixture_root: Path | None = None,
                        prepare_fresh_fixture: bool = False) -> Iterator[dict]:
    """Acquire and RETAIN all known local locks until exiting this context.

    Real paths require root and existing operator-owned hold. Fixture paths
    require a private marked /tmp directory. Busy or missing locks fail closed
    and release any previously acquired locks; never block or drain a game.

    A successful yield is strictly LOCAL and PARTIAL; it is not an Agent ACK
    and must not be used to approve a release or a live update.
    """
    if (type(transaction_id) is not str or not _TX.fullmatch(transaction_id)
            or type(release_sha256) is not str
            or not _SHA.fullmatch(release_sha256)
            or type(expected_controller_uid) is not int
            or type(expected_worker_uid) is not int
            or min(expected_controller_uid, expected_worker_uid) < 0):
        raise LocalScopeLeaseBlocked("invalid_transaction_or_lock_owner_pin")
    if type(prepare_fresh_fixture) is not bool or (
            prepare_fresh_fixture and fixture_root is None):
        raise LocalScopeLeaseBlocked("fresh_preparation_fixture_only")
    controller_lock = Path(controller_lock)
    worker_lock_dir = Path(worker_lock_dir)
    hold_path = Path(hold_path)
    pending_path = Path(pending_path)
    if fixture_root is None:
        if (os.geteuid() != 0 or controller_lock != CONTROLLER_LOCK
                or worker_lock_dir != WORKER_LOCK_DIR
                or hold_path != HOLD_PATH or pending_path != PENDING_PATH):
            raise LocalScopeLeaseBlocked("production_path_requires_root")
        owner = 0
        root = None
    else:
        root = _trusted_fixture_root(Path(fixture_root))
        owner = os.geteuid()
        for path in (controller_lock, worker_lock_dir, hold_path, pending_path):
            if not path.is_absolute() or root not in path.parents:
                raise LocalScopeLeaseBlocked("fixture_lock_path_outside_root")

    # Inspect roots and parent inodes BEFORE taking locks. No file creation.
    _directory_chain(controller_lock.parent, fixture_root=root, owner=owner)
    _directory_chain(worker_lock_dir, fixture_root=root, owner=owner)
    _directory_chain(hold_path.parent, fixture_root=root, owner=owner)
    _directory_chain(pending_path.parent, fixture_root=root, owner=owner)
    hold = _hold_module()
    if prepare_fresh_fixture:
        _require_absent(hold_path, pending_path,
                        pending_path.parent / "no-drain-release-binding.json")
    else:
        _check_hold(hold, hold_path, pending_path, tx=transaction_id, owner=owner)
    expected_files = {name + ".lock" for name in WORKERS}
    if ({p.name for p in worker_lock_dir.iterdir()} != expected_files):
        raise LocalScopeLeaseBlocked("worker_lock_inventory_incomplete_or_unexpected")

    acquired: list[int] = []
    lock_paths: list[tuple[Path, int]] = []
    try:
        for path, uid in (
            (controller_lock, expected_controller_uid),
            *((worker_lock_dir / (name + ".lock"), expected_worker_uid)
              for name in WORKERS),
        ):
            fd = _open_existing_lock(path, owner_uid=uid)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError) as exc:
                os.close(fd)
                raise LocalScopeLeaseBlocked("controller_or_worker_operation_in_flight") from exc
            acquired.append(fd)
            lock_paths.append((path, uid))
        if prepare_fresh_fixture:
            evidence_checkpoint = _fresh_fixture_preparation(
                hold, hold_path, pending_path, tx=transaction_id,
                sha=release_sha256, owner=owner)
        else:
            def evidence_checkpoint():
                _check_hold(hold, hold_path, pending_path,
                            tx=transaction_id, owner=owner)

        def checkpoint():
            for (path, uid), fd in zip(lock_paths, acquired):
                named, held = path.lstat(), os.fstat(fd)
                if ((named.st_dev, named.st_ino) != (held.st_dev, held.st_ino)
                        or not stat.S_ISREG(named.st_mode)
                        or named.st_uid != uid or named.st_nlink != 1
                        or named.st_size != 0
                        or stat.S_IMODE(named.st_mode) != 0o600):
                    raise LocalScopeLeaseBlocked("retained_lock_identity_changed")
            evidence_checkpoint()

        checkpoint()
        yield {
            "kind": "DSM928LocalScopeLease",
            "transaction_id": transaction_id,
            "release_sha256": release_sha256,
            "status": "local_kernel_fences_retained",
            "controller_http_lock_exclusively_held": True,
            "worker_lock_inodes_exclusively_held": len(WORKERS),
            "fresh_durable_fixture_evidence": prepare_fresh_fixture,
            "checkpoint": checkpoint,
            "controller_routes_opted_in_verified": False,
            "worker_process_inventory_verified": False,
            "all_mutators_fenced": False,
            "remote_agents_acked": False,
            "external_jobs_acked": False,
            "durable_cross_host_recovery_verified": False,
            "live_no_drain_authorized": False,
        }
        checkpoint()
    except LocalScopeLeaseBlocked:
        raise
    except (OSError, ValueError) as exc:
        raise LocalScopeLeaseBlocked("local_fence_unavailable") from exc
    finally:
        for fd in reversed(acquired):
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
