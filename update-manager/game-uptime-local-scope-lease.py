#!/usr/bin/env python3
"""#928: retain Controller/Worker kernel fences through a bounded local scope.

This is a real flock-based LOCAL primitive (not a synthetic ACK), but it
covers ONLY 3 Controller Agent HTTP routes and 9 registered Worker cycles.
It cannot attest other APIs, Agents on other hosts, external jobs, game PIDs
or a release's authenticity, and NEVER grants a live no-drain update.

Fresh installed preparation is an explicit root-only retained-scope
primitive, bound to the complete inventory and absolute lease window.
Installed code imports Agent primitives from the audited root snapshot.
It does not authorize apply, restart services or clear installed evidence.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import fcntl
from importlib.machinery import SourceFileLoader
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import json
import hashlib
import subprocess
from typing import Callable, Iterator

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


def _runtime_dir(installed: bool) -> Path:
    if not installed:
        return Path(__file__).resolve().parents[1] / "agents/linux/runtime"
    root = Path("/usr/local/libexec/capivara-dsm-928-agent")
    for folder in (Path("/usr"), Path("/usr/local"), Path("/usr/local/libexec"), root):
        _safe_directory(folder, owner=0)
    modules = ("game_uptime_ssh_transport", "game_uptime_hold_coordinator",
               "game_uptime_maintenance_hold", "game_uptime_transaction_binding",
               "game_uptime_privileged_flock", "game_uptime_finalization_flock",
               "game_uptime_privileged_journal_witness",
               "game_uptime_wire_replay_service", "game_uptime_durable_wire_replay")
    for name in modules:
        path = root / (name + ".py")
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_nlink != 1
                or not 0 < info.st_size <= 1024 * 1024):
            raise LocalScopeLeaseBlocked("untrusted_installed_agent_snapshot")
        audited = Path("/usr/local/libexec/capivara-dsm-928-updater/agents/linux/runtime") / path.name
        for folder in (audited.parent.parent.parent.parent, audited.parent.parent.parent,
                       audited.parent.parent, audited.parent):
            _safe_directory(folder, owner=0)
        source = audited.lstat()
        if (not stat.S_ISREG(source.st_mode) or source.st_uid != 0
                or source.st_mode & 0o022 or source.st_nlink != 1
                or not 0 < source.st_size <= 1024 * 1024
                or path.read_bytes() != audited.read_bytes()):
            raise LocalScopeLeaseBlocked("installed_agent_snapshot_revision_mismatch")
        # Never reuse a module previously imported from a checkout or
        # mutable installation tree in an installed privileged transaction.
        loaded = sys.modules.get(name)
        if loaded is not None and getattr(loaded, "__file__", None) != str(path):
            raise LocalScopeLeaseBlocked("conflicting_installed_agent_module")
    return root


def _hold_module(runtime_dir):
    path = Path(runtime_dir) / "game_uptime_maintenance_hold.py"
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


def _fresh_preparation(hold, hold_path: Path, pending_path: Path,
                       *, tx: str, sha: str, owner: int,
                       agent_ids: list[str] | None, runtime_dir: Path,
                       shared_lease_window: tuple[int, int] | None = None):
    """Create once, under retained locks; never accept a prior journal."""
    binding_path = pending_path.parent / "no-drain-release-binding.json"
    inventory_path = pending_path.parent / "no-drain-agent-inventory.json"
    _require_absent(hold_path, pending_path, binding_path, inventory_path)
    runtime = str(runtime_dir)
    sys.path.insert(0, runtime)
    try:
        from game_uptime_hold_coordinator import prepare_root_only
        from game_uptime_transaction_binding import binding_for_hold
        from game_uptime_durable_wire_replay import _root_pending
        from game_uptime_wire_replay_service import read_inventory
    finally:
        sys.path.remove(runtime)
    try:
        timing = {}
        if shared_lease_window is not None:
            issued, expires = shared_lease_window
            if not issued <= time.time() < expires:
                raise LocalScopeLeaseBlocked("shared_local_lease_expired")
            timing = {"now": issued, "ttl_seconds": expires - issued}
        prepared = prepare_root_only(
            transaction_id=tx, release_sha256=sha, trusted_uid=owner,
            journal_path=pending_path, hold_path=hold_path,
            binding_path=binding_path, expected_agent_ids=agent_ids, **timing)
        if (prepared.get("release_identity_bound_locally") is not True
                or prepared.get("operator_agent_inventory_persisted")
                   is not (agent_ids is not None)
                or prepared.get("live_no_drain_authorized") is not False):
            raise LocalScopeLeaseBlocked("fresh_preparation_invalid")
        checkpoint = _prepared_evidence_checkpoint(
            hold, hold_path, pending_path, tx=tx, sha=sha,
            owner=owner, agent_ids=agent_ids, runtime_dir=runtime_dir,
            shared_lease_window=shared_lease_window)
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalScopeLeaseBlocked("fresh_transaction_preparation_blocked") from exc
    return checkpoint


def _prepared_evidence_checkpoint(hold, hold_path: Path, pending_path: Path,
                                  *, tx: str, sha: str, owner: int,
                                  agent_ids: list[str] | None,
                                  runtime_dir: Path,
                                  shared_lease_window: tuple[int, int] | None = None):
    """Validate exact durable evidence, without creating or clearing a hold."""
    binding_path = pending_path.parent / "no-drain-release-binding.json"
    inventory_path = pending_path.parent / "no-drain-agent-inventory.json"
    runtime = str(runtime_dir)
    sys.path.insert(0, runtime)
    try:
        from game_uptime_transaction_binding import binding_for_hold
        from game_uptime_durable_wire_replay import _root_pending
        from game_uptime_wire_replay_service import read_inventory
    finally:
        sys.path.remove(runtime)
    paths = (hold_path, pending_path, binding_path)
    if agent_ids is not None:
        paths += (inventory_path,)
    identities = tuple(_evidence_identity(path) for path in paths)

    def checkpoint():
        observed = hold.observe(path=hold_path, trusted_uid=owner,
                                pending_path=pending_path)
        if (observed.get("active") is not True
                or observed.get("reason") != "root_owned_maintenance_hold"
                or observed.get("transaction_id") != tx):
            raise LocalScopeLeaseBlocked("fresh_hold_invalid")
        if shared_lease_window is not None and (
                (observed["issued_at"], observed["expires_at"]) != shared_lease_window
                or not observed["issued_at"] <= time.time() < observed["expires_at"]):
            raise LocalScopeLeaseBlocked("shared_local_lease_changed")
        _root_pending(pending_path, owner, tx,
                      observed["issued_at"], observed["expires_at"])
        pin = binding_for_hold(observed, path=binding_path, trusted_uid=owner)
        if agent_ids is not None:
            inventory = read_inventory(path=inventory_path, trusted_uid=owner)
            expected = {
                "kind": "DSM928OperatorAgentInventory",
                "schema_version": 1, "transaction_id": tx,
                "release_sha256": sha, "issued_at": observed["issued_at"],
                "expires_at": observed["expires_at"],
                "agent_ids": sorted(agent_ids),
            }
            if inventory != expected:
                raise LocalScopeLeaseBlocked("fixture_agent_inventory_changed")
        if (pin is None or pin.get("release_sha256") != sha
                or tuple(_evidence_identity(path) for path in paths) != identities):
            raise LocalScopeLeaseBlocked("fresh_transaction_evidence_changed")
    checkpoint()
    return checkpoint


def _retain_agent_operations(stack: ExitStack, runtime_dir: Path,
                             *, owner: int, installed: bool = False):
    """Retain both preprovisioned Agent lock families; never provision them."""
    runtime = str(_runtime_dir(installed))
    sys.path.insert(0, runtime)
    try:
        from game_uptime_privileged_flock import exclusive_privileged_helper_lock
        from game_uptime_finalization_flock import exclusive_finalization_lock
    finally:
        sys.path.remove(runtime)
    helper = runtime_dir / "agent-privileged-operations.lock"
    child = runtime_dir / "agent-finalization-operations.lock"
    try:
        paths = (helper, child)
        identities = tuple(_evidence_identity(path) for path in paths)
        stack.enter_context(exclusive_privileged_helper_lock(
            path=helper, trusted_uid=owner))
        if installed:
            stack.enter_context(exclusive_finalization_lock(path=child))
        else:
            stack.enter_context(exclusive_finalization_lock(
                path=child, trusted_uid=owner, group_gid=os.getegid()))

        def checkpoint():
            if tuple(_evidence_identity(path) for path in paths) != identities:
                raise LocalScopeLeaseBlocked("agent_operation_lock_identity_changed")
        checkpoint()
        return checkpoint
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalScopeLeaseBlocked("agent_operation_lock_unavailable") from exc


@contextmanager
def retain_local_scopes(*, transaction_id: str, release_sha256: str,
                        expected_controller_uid: int,
                        expected_worker_uid: int,
                        controller_lock: Path = CONTROLLER_LOCK,
                        worker_lock_dir: Path = WORKER_LOCK_DIR,
                        hold_path: Path = HOLD_PATH,
                        pending_path: Path = PENDING_PATH,
                        fixture_root: Path | None = None,
                        prepare_fresh_fixture: bool = False,
                        expected_fixture_agent_ids: list[str] | None = None,
                        inspect_existing_prepared: bool = False,
                        expected_recovery_agent_ids: list[str] | None = None,
                        prepare_fresh_installed: bool = False,
                        expected_installed_agent_ids: list[str] | None = None,
                        shared_lease_window: tuple[int, int] | None = None,
                        before_prepare: Callable[[], None] | None = None) -> Iterator[dict]:
    """Acquire and RETAIN all known local locks until exiting this context.

    Real paths require root and independently reviewed inventory/lease for
    fresh preparation, or existing operator-owned hold. Fixture paths
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
    if (type(prepare_fresh_installed) is not bool
            or (prepare_fresh_installed and (fixture_root is not None
                or prepare_fresh_fixture or shared_lease_window is None))
            or (expected_installed_agent_ids is None) == prepare_fresh_installed):
        raise LocalScopeLeaseBlocked("invalid_installed_preparation_scope")
    if prepare_fresh_installed:
        ids = expected_installed_agent_ids
        if (type(ids) is not list or not 1 <= len(ids) <= 64
                or any(type(item) is not str
                       or not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", item)
                       for item in ids) or len(set(ids)) != len(ids)):
            raise LocalScopeLeaseBlocked("invalid_installed_agent_inventory")
        expected_installed_agent_ids = sorted(ids)
    if shared_lease_window is not None:
        if (type(shared_lease_window) is not tuple or len(shared_lease_window) != 2
                or any(type(t) is not int for t in shared_lease_window)
                or not 0 < shared_lease_window[0] <= time.time() < shared_lease_window[1]
                    <= shared_lease_window[0] + 900
                or not (prepare_fresh_fixture or prepare_fresh_installed
                        or inspect_existing_prepared)):
            raise LocalScopeLeaseBlocked("invalid_shared_local_lease_window")
    fresh = prepare_fresh_fixture or prepare_fresh_installed
    if before_prepare is not None and (not fresh or not callable(before_prepare)):
        raise LocalScopeLeaseBlocked("invalid_preparation_guard")
    if expected_fixture_agent_ids is not None:
        if (not prepare_fresh_fixture or type(expected_fixture_agent_ids) is not list
                or not 1 <= len(expected_fixture_agent_ids) <= 64
                or any(type(item) is not str
                       or not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", item)
                       for item in expected_fixture_agent_ids)
                or len(set(expected_fixture_agent_ids)) != len(expected_fixture_agent_ids)):
            raise LocalScopeLeaseBlocked("invalid_fixture_agent_inventory")
        expected_fixture_agent_ids = sorted(expected_fixture_agent_ids)
    if (type(inspect_existing_prepared) is not bool
            or (inspect_existing_prepared and fresh)
            or (expected_recovery_agent_ids is None) != (not inspect_existing_prepared)):
        raise LocalScopeLeaseBlocked("invalid_recovery_inspection_scope")
    if inspect_existing_prepared:
        ids = expected_recovery_agent_ids
        if (type(ids) is not list or not 1 <= len(ids) <= 64
                or any(type(item) is not str
                       or not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", item)
                       for item in ids) or len(set(ids)) != len(ids)):
            raise LocalScopeLeaseBlocked("invalid_recovery_agent_inventory")
        expected_recovery_agent_ids = sorted(ids)
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
    runtime_dir = _runtime_dir(root is None)
    hold = _hold_module(runtime_dir)
    if fresh:
        _require_absent(hold_path, pending_path,
                        pending_path.parent / "no-drain-release-binding.json",
                        pending_path.parent / "no-drain-agent-inventory.json")
    elif not inspect_existing_prepared:
        _check_hold(hold, hold_path, pending_path, tx=transaction_id, owner=owner)
    expected_files = {name + ".lock" for name in WORKERS}
    if ({p.name for p in worker_lock_dir.iterdir()} != expected_files):
        raise LocalScopeLeaseBlocked("worker_lock_inventory_incomplete_or_unexpected")

    acquired: list[int] = []
    agent_locks = ExitStack()
    lock_paths: list[tuple[Path, int]] = []
    retained = True
    try:
        if root is None:
            runtime = str(runtime_dir)
            sys.path.insert(0, runtime)
            try:
                from game_uptime_privileged_flock import exclusive_update_admission
            finally:
                sys.path.remove(runtime)
            agent_locks.enter_context(exclusive_update_admission(provision=False))
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
        if fresh:
            agent_checkpoint = _retain_agent_operations(
                agent_locks, controller_lock.parent, owner=owner, installed=root is None)
            if before_prepare is not None:
                before_prepare()
            evidence_checkpoint = _fresh_preparation(
                hold, hold_path, pending_path, tx=transaction_id,
                sha=release_sha256, owner=owner, runtime_dir=runtime_dir,
                agent_ids=(expected_installed_agent_ids if prepare_fresh_installed
                           else expected_fixture_agent_ids),
                shared_lease_window=shared_lease_window)
        elif inspect_existing_prepared:
            # Separate inspection path: an existing journal is still a
            # hard blocker for fresh apply, including in the composite bridge.
            agent_checkpoint = _retain_agent_operations(
                agent_locks, controller_lock.parent, owner=owner,
                installed=root is None)
            evidence_checkpoint = _prepared_evidence_checkpoint(
                hold, hold_path, pending_path, tx=transaction_id,
                sha=release_sha256, owner=owner,
                agent_ids=expected_recovery_agent_ids, runtime_dir=runtime_dir,
                shared_lease_window=shared_lease_window)
        else:
            def evidence_checkpoint():
                _check_hold(hold, hold_path, pending_path,
                            tx=transaction_id, owner=owner)

        def checkpoint():
            if not retained or released:
                raise LocalScopeLeaseBlocked("local_scope_no_longer_retained")
            for (path, uid), fd in zip(lock_paths, acquired):
                named, held = path.lstat(), os.fstat(fd)
                if ((named.st_dev, named.st_ino) != (held.st_dev, held.st_ino)
                        or not stat.S_ISREG(named.st_mode)
                        or named.st_uid != uid or named.st_nlink != 1
                        or named.st_size != 0
                        or stat.S_IMODE(named.st_mode) != 0o600):
                    raise LocalScopeLeaseBlocked("retained_lock_identity_changed")
            if fresh or inspect_existing_prepared:
                agent_checkpoint()
            evidence_checkpoint()

        released = False

        def release_host(decision, verify_terminal):
            nonlocal released
            if root is not None or released or not inspect_existing_prepared:
                raise LocalScopeLeaseBlocked("reviewed_installed_terminal_release_required")
            from game_uptime_hold_coordinator import _archive_confirmed_hold
            result = _archive_confirmed_hold(
                marker=hold_path, pending=pending_path, transaction_id=transaction_id,
                decision=decision, uid=owner, checkpoint=verify_terminal, installed=True)
            released = True
            return result

        def release_fixture(outcome, journal_sha256, confirmation_sha256):
            nonlocal released
            if root is None or released or not inspect_existing_prepared:
                raise LocalScopeLeaseBlocked("fixture_terminal_release_only")
            runtime = str(Path(__file__).resolve().parents[1] / "agents/linux/runtime")
            sys.path.insert(0, runtime)
            try:
                from game_uptime_hold_coordinator import _archive_fixture_hold, _terminal_decision
            finally:
                sys.path.remove(runtime)
            decision = _terminal_decision(outcome, journal_sha256)
            if (type(confirmation_sha256) is not str
                    or not _SHA.fullmatch(confirmation_sha256)):
                raise LocalScopeLeaseBlocked("invalid_global_confirmation_digest")
            result = _archive_fixture_hold(
                marker=hold_path, pending=pending_path, transaction_id=transaction_id,
                decision={**decision, "confirmation_sha256": confirmation_sha256},
                uid=owner, checkpoint=checkpoint)
            released = True
            return result

        checkpoint()
        yield {
            "kind": "DSM928LocalScopeLease",
            "transaction_id": transaction_id,
            "release_sha256": release_sha256,
            "status": "local_kernel_fences_retained",
            "controller_http_lock_exclusively_held": True,
            "worker_lock_inodes_exclusively_held": len(WORKERS),
            "fresh_durable_fixture_evidence": prepare_fresh_fixture,
            "fresh_installed_local_evidence": prepare_fresh_installed,
            "installed_agent_inventory_retained": prepare_fresh_installed,
            "shared_lease_window": shared_lease_window,
            "existing_prepared_recovery_inspection_only": inspect_existing_prepared,
            "recovery_scope_inodes_retained": inspect_existing_prepared,
            "fixture_agent_inventory_retained": expected_fixture_agent_ids is not None,
            "fixture_privileged_helper_lock_retained": prepare_fresh_fixture,
            "fixture_finalization_child_lock_retained": prepare_fresh_fixture,
            "checkpoint": checkpoint, "release_fixture": release_fixture,
            "release_host": release_host,
            "controller_routes_opted_in_verified": False,
            "worker_process_inventory_verified": False,
            "all_mutators_fenced": False,
            "remote_agents_acked": False,
            "external_jobs_acked": False,
            "durable_cross_host_recovery_verified": False,
            "live_no_drain_authorized": False,
        }
        if not released:
            checkpoint()
    except LocalScopeLeaseBlocked:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalScopeLeaseBlocked("local_fence_unavailable") from exc
    finally:
        retained = False
        try:
            agent_locks.close()
        finally:
            for fd in reversed(acquired):
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)



def _validate_controller_agent_inventory(rows, expected_ids, hybrid_id):
    """Only a formally retired and empty Agent may be omitted."""
    if type(rows) is not list or not 1 <= len(rows) <= 4096:
        raise LocalScopeLeaseBlocked("controller_agent_inventory_unavailable")
    seen, retained = set(), {}
    for row in rows:
        if (type(row) is not dict
                or set(row) != {"id", "status", "role", "instances",
                                "credentials", "commands"}
                or type(row["id"]) is not str
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", row["id"])
                or row["id"] in seen
                or row["role"] not in ("agent", "hybrid")
                or any(type(row[k]) is not int or row[k] < 0
                       for k in ("instances", "credentials", "commands"))):
            raise LocalScopeLeaseBlocked("invalid_controller_agent_inventory_row")
        agent = row["id"]
        seen.add(agent)
        if row["status"] == "decommissioned":
            if any(row[k] for k in ("instances", "credentials", "commands")):
                raise LocalScopeLeaseBlocked("retired_agent_still_has_operational_state")
            continue
        # Offline, disabled, pairing and other non-retired Agents cannot
        # silently disappear. Require the operator to resolve those states.
        if row["status"] != "active":
            raise LocalScopeLeaseBlocked("nonactive_agent_requires_review")
        if row["role"] != ("hybrid" if agent == hybrid_id else "agent"):
            raise LocalScopeLeaseBlocked("controller_agent_role_mismatch")
        retained[agent] = row["role"]
    if (hybrid_id not in retained
            or (expected_ids is not None and set(retained) != set(expected_ids))):
        raise LocalScopeLeaseBlocked("controller_agent_inventory_mismatch")
    return tuple(sorted(retained.items()))


# Only durable operation/command queues, not desired-state or policy rows.
# Unknown statuses are deliberately nonterminal. Absence of outstanding
# records is necessary but does NOT attest detached processes or cron jobs.
_COMMON_TERMINAL = ("completed", "failed", "cancelled", "canceled",
                    "succeeded", "success", "skipped", "expired",
                    "rolled_back", "rejected", "aborted")
_JOB_TERMINAL = {
    name: _COMMON_TERMINAL for name in (
        "operations", "agent_instance_commands", "agent_game_data_jobs",
        "agent_instance_provisioning", "backup_jobs", "automation_runs",
        "yarax_admin_operations", "instance_console_commands",
        "instance_file_commands", "instance_resource_commands",
        "instance_update_runs", "instance_maintenance_runs",
        "artifact_transfers", "dayz_operations", "native_restart_commands",
    )
}
_JOB_TERMINAL["notification_outbox"] = ("delivered", "failed", "cancelled")
_JOB_TERMINAL["broadcast_deliveries"] = (*_COMMON_TERMINAL, "acknowledged")
_JOB_TERMINAL["ha_failover_operations"] = _COMMON_TERMINAL


def _job_inventory_sql():
    # Identifiers and status literals come exclusively from the fixed
    # audited schema contract above, never the database or operator input.
    queries = []
    for name, states in sorted(_JOB_TERMINAL.items()):
        field = "state" if name == "ha_failover_operations" else "status"
        terminal = ",".join("'" + value + "'" for value in states)
        queries.append("SELECT '" + name + "' AS queue, COUNT(*) AS outstanding "
                       "FROM public." + name + " WHERE " + field + " IS NULL OR "
                       + field + " NOT IN (" + terminal + ")")
    return " UNION ALL ".join(queries)


def _validate_job_inventory(rows):
    if type(rows) is not list or len(rows) != len(_JOB_TERMINAL):
        raise LocalScopeLeaseBlocked("controller_job_inventory_incomplete")
    seen = {}
    for row in rows:
        if (type(row) is not dict or set(row) != {"queue", "outstanding"}
                or type(row["queue"]) is not str or row["queue"] not in _JOB_TERMINAL
                or row["queue"] in seen or type(row["outstanding"]) is not int
                or row["outstanding"] < 0):
            raise LocalScopeLeaseBlocked("invalid_controller_job_inventory")
        seen[row["queue"]] = row["outstanding"]
    busy = [name for name, count in sorted(seen.items()) if count]
    if busy:
        raise LocalScopeLeaseBlocked("controller_jobs_not_terminal:" + ",".join(busy))
    return tuple(sorted(seen.items()))


def _stable_daemon_inventory(controller, workers, alert, expected_uid):
    """Immutable identity witness, NOT permission to update.

    Include the complete Controller/Worker/alert group in every retained
    checkpoint. Equal Agent registry rows cannot hide a daemon restart.
    """
    if (type(expected_uid) is not int or expected_uid <= 0
            or controller.get("identity_verified") is not True
            or controller.get("flock_opted_in_verified") is not True
            or workers.get("supervisor_verified") is not True
            or workers.get("all_nine_workers_verified") is not True
            or workers.get("observed_worker_count") != len(WORKERS)
            or type(workers.get("worker_identities")) is not dict
            or set(workers["worker_identities"]) != set(WORKERS)
            or alert.get("uid") != expected_uid):
        raise LocalScopeLeaseBlocked("installed_daemon_inventory_incomplete")
    entries = {"controller": controller, "worker_supervisor": workers.get("supervisor_identity"),
               "alert_engine": alert, **workers["worker_identities"]}
    if any(type(item) is not dict
           or type(item.get("pid")) is not int or item["pid"] <= 1
           or type(item.get("start_ticks")) is not int or item["start_ticks"] <= 0
           for item in entries.values()):
        raise LocalScopeLeaseBlocked("installed_daemon_process_witness_invalid")
    if len({item["pid"] for item in entries.values()}) != len(entries):
        raise LocalScopeLeaseBlocked("installed_daemon_process_witness_duplicate")
    return tuple(sorted((name, item["pid"], item["start_ticks"])
                        for name, item in entries.items()))


def _read_installed_controller_agents(expected_ids, hybrid_id, *, expected_uid):
    """Query the actual installed PostgreSQL Controller under its service UID.

    Never import the mutable installed database package into the root
    coordinator or disclose the daemon environment/credentials. No database
    migration, enrollment, or write is performed. Other backends remain
    blocked until an equivalent read-only operational path is provided.
    """
    if os.geteuid() != 0:
        raise LocalScopeLeaseBlocked("root_inventory_observation_required")
    path = Path(__file__).with_name("game-uptime-live-daemon-identity.py")
    loader = SourceFileLoader("dsm928_scope_controller_identity", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    identity = importlib.util.module_from_spec(spec)
    loader.exec_module(identity)
    before = identity._controller_identity()
    if before.get("identity_verified") is not True or before.get("flock_opted_in_verified") is not True:
        raise LocalScopeLeaseBlocked("installed_controller_identity_unverified")
    pid = before["pid"]
    proc = Path("/proc") / str(pid)
    try:
        status = dict(line.split(":", 1) for line in (proc / "status").read_text().splitlines()
                      if ":" in line)
        uids, gids = status["Uid"].split(), status["Gid"].split()
        if len(uids) != 4 or len(gids) != 4 or len(set(uids)) != 1 or len(set(gids)) != 1:
            raise ValueError("unexpected service credentials")
        uid, gid = int(uids[0]), int(gids[0])
        if uid <= 0 or gid <= 0 or uid != expected_uid:
            raise ValueError("controller service account mismatch")
        alert_before = identity._alert_engine_identity(expected_uid=uid)
        daemon_before = _stable_daemon_inventory(
            before, identity._workers_identity(), alert_before, expected_uid)
        groups = [int(x) for x in status["Groups"].split()]
        if 0 in groups:
            raise ValueError("privileged controller group")
        raw = (proc / "environ").read_bytes()
        if len(raw) > 262144 or not raw.endswith(b"\x00"):
            raise ValueError("controller environment unavailable")
        allowed = {"DSM_DATABASE_DRIVER", "DSM_DATABASE_NAME", "DSM_DATABASE_HOST",
                   "DSM_DATABASE_PORT", "DSM_DATABASE_USER",
                   "DSM_DATABASE_PASSWORD_FILE", "DSM_DATABASE_TLS"}
        env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"}
        for entry in raw[:-1].split(b"\x00"):
            key, _, value = entry.partition(b"=")
            name = key.decode("ascii")
            if name in allowed:
                if name in env:
                    raise ValueError("duplicate database configuration")
                env[name] = value.decode("utf-8")
        if env.get("DSM_DATABASE_DRIVER") not in ("postgresql", "postgres", "pgsql"):
            raise ValueError("operational inventory requires PostgreSQL")
        if identity._controller_identity() != before:
            raise ValueError("controller identity changed before inventory")
        # The fixed SQL is independent of caller-supplied IDs. Correlated
        # counts include every Agent, including retired registrations.
        sql = """
SELECT a.id, a.status, n.role,
       (SELECT COUNT(*) FROM public.instances i WHERE i.node_id=a.node_id) AS instances,
       (SELECT COUNT(*) FROM public.agent_credentials c WHERE c.agent_id=a.id
          AND c.status='active') AS credentials,
       (SELECT COUNT(*) FROM public.agent_instance_commands j WHERE j.agent_id=a.id
          AND j.status IN ('queued','delivered')) AS commands
FROM public.agents a LEFT JOIN public.nodes n ON n.id=a.node_id
ORDER BY a.id LIMIT 4097
"""
        reader = """
import json, sys
sys.path.insert(0, "/opt/dsm/database")
from runtime_backend import backend_from_environment
backend = backend_from_environment()
if backend.name != "postgresql":
    raise SystemExit(2)
with backend.connect() as connection:
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '5s'")
        rows = connection.execute(sys.argv[1]).fetchall()
        jobs = connection.execute(sys.argv[2]).fetchall()
        print(json.dumps({"agents": [dict(row) for row in rows],
                          "jobs": [dict(row) for row in jobs]}, separators=(",", ":")))
"""
        result = subprocess.run(
            ("/usr/bin/python3", "-I", "-B", "-c", reader, sql, _job_inventory_sql()),
            user=uid, group=gid, extra_groups=groups,
            env=env, cwd="/", stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=12)
        if (result.returncode != 0 or len(result.stdout) > 1048576
                or identity._controller_identity() != before
                or identity._alert_engine_identity(expected_uid=uid) != alert_before):
            raise ValueError("controller inventory observation failed")
        observed = json.loads(result.stdout)
        if type(observed) is not dict or set(observed) != {"agents", "jobs"}:
            raise ValueError("controller inventory contract invalid")
        agents = _validate_controller_agent_inventory(observed["agents"],
                                                       expected_ids, hybrid_id)
        jobs = _validate_job_inventory(observed["jobs"])
        daemon_after = _stable_daemon_inventory(
            identity._controller_identity(), identity._workers_identity(),
            identity._alert_engine_identity(expected_uid=uid), expected_uid)
        if daemon_before != daemon_after:
            raise LocalScopeLeaseBlocked("installed_daemon_identity_changed")
        # Preserve exact registry counts as well as the partition. A change
        # in instances/credentials is evidence drift even if IDs are unchanged.
        registry = tuple(sorted((row["id"], row["status"], row["role"],
                                 row["instances"], row["credentials"], row["commands"])
                                for row in observed["agents"]))
        return (agents, jobs, daemon_before, registry)
    except LocalScopeLeaseBlocked:
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        raise LocalScopeLeaseBlocked("controller_agent_inventory_unverified") from exc


def _validate_restart_inventory(before, after):
    """Validate a replacement witness without granting installed admission.

    Registry and job inventory must be identical. Only Controller and the
    Worker group may change; the auxiliary alert writer must remain intact.
    """
    if (type(before) is not tuple or type(after) is not tuple
            or len(before) != 4 or len(after) != 4
            or any(before[i] != after[i] for i in (0, 1, 3))):
        raise LocalScopeLeaseBlocked("restart_registry_or_jobs_changed")
    expected = {"controller", "worker_supervisor", "alert_engine", *WORKERS}
    def identities(rows):
        if type(rows) is not tuple or len(rows) != len(expected):
            raise LocalScopeLeaseBlocked("restart_daemon_inventory_invalid")
        result = {}
        for name, pid, ticks in rows:
            if (name not in expected or name in result
                    or type(pid) is not int or pid <= 1
                    or type(ticks) is not int or ticks <= 0):
                raise LocalScopeLeaseBlocked("restart_daemon_identity_invalid")
            result[name] = (pid, ticks)
        if len({pid for pid, _ in result.values()}) != len(expected):
            raise LocalScopeLeaseBlocked("restart_daemon_pid_duplicate")
        return result
    old, new = identities(before[2]), identities(after[2])
    if old["alert_engine"] != new["alert_engine"]:
        raise LocalScopeLeaseBlocked("restart_alert_engine_changed")
    replaced = expected - {"alert_engine"}
    if ({old[name] for name in replaced} & {new[name] for name in replaced}
            or any(new[name][1] < old[name][1] for name in replaced)):
        raise LocalScopeLeaseBlocked("restart_daemon_replacement_unverified")
    return {"status": "replacement_inventory_verified_only",
            "replacement_count": len(replaced),
            "live_no_drain_authorized": False}


def _restart_transition_payload(scope, before, after, *, sequence, previous_sha256):
    """Build a canonical diagnostic receipt; never replace the original witness."""
    if (type(sequence) is not int or sequence not in (1, 2)
            or type(previous_sha256) is not str
            or not _SHA.fullmatch(previous_sha256)
            or type(scope) is not dict
            or type(scope.get("transaction_id")) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", scope["transaction_id"])
            or type(scope.get("release_sha256")) is not str
            or not _SHA.fullmatch(scope["release_sha256"])):
        raise LocalScopeLeaseBlocked("invalid_restart_transition_binding")
    _validate_restart_inventory(before, after)
    def digest(inventory):
        return hashlib.sha256(json.dumps(
            inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"kind": "DSM928DaemonRestartTransitionWitness",
            "schema_version": 1, "transaction_id": scope["transaction_id"],
            "release_sha256": scope["release_sha256"], "sequence": sequence,
            "previous_sha256": previous_sha256,
            "before_inventory_sha256": digest(before),
            "after_inventory_sha256": digest(after),
            "live_no_drain_authorized": False}


def _persist_restart_transition(scope, before, after, *, sequence,
                                root_file, persist_receipt, fence_checkpoint):
    """Append a bound receipt under the existing root-owned state directory.

    This internal primitive does not authorize restart or recovery admission.
    The caller must retain the independent local and game fences.
    """
    if os.geteuid() != 0 or type(sequence) is not int or sequence not in (1, 2):
        raise LocalScopeLeaseBlocked("root_restart_transition_required")
    tx = scope.get("transaction_id")
    if type(tx) is not str or not _TX.fullmatch(tx):
        raise LocalScopeLeaseBlocked("invalid_restart_transition_binding")
    directory = PENDING_PATH.parent
    _directory_chain(directory, fixture_root=None, owner=0)
    original = directory / ("daemon-witness-" + tx + ".json")
    previous = original if sequence == 1 else directory / (
        "daemon-restart-" + tx + "-1.json")
    destination = directory / ("daemon-restart-" + tx + "-" + str(sequence) + ".json")
    fence_checkpoint()
    raw = root_file(previous, 32768)
    prior = json.loads(raw)
    if (raw != (json.dumps(prior, sort_keys=True, separators=(",", ":")) + "\n").encode()
            or prior.get("transaction_id") != tx
            or prior.get("release_sha256") != scope.get("release_sha256")
            or prior.get("live_no_drain_authorized") is not False
            or prior.get("kind") != ("DSM928InstalledDaemonInventoryWitness" if sequence == 1
                                    else "DSM928DaemonRestartTransitionWitness")
            or (sequence == 2 and prior.get("sequence") != 1)):
        raise LocalScopeLeaseBlocked("restart_transition_previous_receipt_invalid")
    payload = _restart_transition_payload(scope, before, after, sequence=sequence,
                                         previous_sha256=hashlib.sha256(raw).hexdigest())
    if payload["before_inventory_sha256"] != prior.get(
            "inventory_sha256" if sequence == 1 else "after_inventory_sha256"):
        raise LocalScopeLeaseBlocked("restart_transition_inventory_chain_mismatch")
    if os.path.lexists(destination):
        raise LocalScopeLeaseBlocked("restart_transition_already_exists")
    fence_checkpoint()
    persist_receipt(destination, payload, 0)
    _check_daemon_witness(root_file(destination, 32768), payload)
    fence_checkpoint()
    return payload


def _validate_restart_receipt_chain(original_raw, receipt_bytes, scope, inventory):
    """Validate recorded transitions without granting recovery admission."""
    if type(receipt_bytes) not in (list, tuple) or len(receipt_bytes) not in (1, 2):
        raise LocalScopeLeaseBlocked("invalid_restart_receipt_count")
    def decode(raw):
        value = json.loads(raw)
        if (type(value) is not dict or raw != (json.dumps(
                value, sort_keys=True, separators=(",", ":")) + "\n").encode()):
            raise LocalScopeLeaseBlocked("noncanonical_restart_receipt")
        return value
    original = decode(original_raw)
    if (original.get("kind") != "DSM928InstalledDaemonInventoryWitness"
            or original.get("schema_version") != 1
            or original.get("live_no_drain_authorized") is not False
            or any(original.get(key) != value for key, value in scope.items())):
        raise LocalScopeLeaseBlocked("restart_original_scope_mismatch")
    previous = original_raw
    digest = original.get("inventory_sha256")
    if type(digest) is not str or not _SHA.fullmatch(digest):
        raise LocalScopeLeaseBlocked("invalid_original_inventory_digest")
    for sequence, raw in enumerate(receipt_bytes, 1):
        receipt = decode(raw)
        after = receipt.get("after_inventory_sha256")
        expected = {"kind": "DSM928DaemonRestartTransitionWitness",
                    "schema_version": 1, "transaction_id": scope["transaction_id"],
                    "release_sha256": scope["release_sha256"], "sequence": sequence,
                    "previous_sha256": hashlib.sha256(previous).hexdigest(),
                    "before_inventory_sha256": digest,
                    "after_inventory_sha256": after,
                    "live_no_drain_authorized": False}
        if (receipt != expected or type(after) is not str
                or not _SHA.fullmatch(after) or after == digest):
            raise LocalScopeLeaseBlocked("invalid_restart_receipt_chain")
        previous, digest = raw, after
    observed = hashlib.sha256(json.dumps(
        inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if observed != digest:
        raise LocalScopeLeaseBlocked("restart_terminal_inventory_mismatch")
    return {"status": "restart_receipt_chain_verified_only",
            "sequence": len(receipt_bytes), "live_no_drain_authorized": False}


def _daemon_witness_payload(scope, inventory):
    """Bind the original inventory (including daemon PIDs) to this lease.

    Store a digest rather than potentially thousands of registry rows.
    Reconnection must compare to the original immutable receipt, not
    establish a fresh baseline after losing the session.
    """
    raw = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"kind": "DSM928InstalledDaemonInventoryWitness", "schema_version": 1,
            **scope, "inventory_sha256": hashlib.sha256(raw).hexdigest(),
            "live_no_drain_authorized": False}


def _check_daemon_witness(raw, payload):
    expected = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if raw != expected:
        raise LocalScopeLeaseBlocked("original_daemon_inventory_witness_changed")


def _check_controller_topology_settled():
    """A Controller restart must not activate the unfenced topology writer."""
    output = subprocess.run(
        ("/usr/bin/systemctl", "show", "dsm-controller-service-topology.service",
         "--property=LoadState,ActiveState,SubState,RemainAfterExit,NeedDaemonReload",
         "--no-pager"),
        check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, text=True, timeout=5,
    ).stdout.splitlines()
    if len(output) != 5 or set(output) != {
            "LoadState=loaded", "ActiveState=active", "SubState=exited",
            "RemainAfterExit=yes", "NeedDaemonReload=no"}:
        raise LocalScopeLeaseBlocked("unfenced_controller_topology_activation")


# These are the root unit entrypoints reachable from the Hybrid worker.
_HYBRID_HELPERS = {
    "backup-restore": "restore_instance_backup.py",
    "files-access": "prepare_customer_files.py",
    "firewall": "reconcile_firewall.py",
    "materialize": "materialize_instance.py",
    "native-command": "native_command.py",
}
_HYBRID_HELPER_SELECTORS = {
    b"CAPIVARA_BACKUP_RESTORE_UNIT_TEMPLATE": b"dsm-hybrid-agent-backup-restore@{command_id}.service",
    b"CAPIVARA_FIREWALL_UNIT_TEMPLATE": b"dsm-hybrid-agent-firewall@{instance_id}.service",
    b"CAPIVARA_HYBRID_FILES_ACCESS_UNIT_TEMPLATE": b"dsm-hybrid-agent-files-access@{instance_id}.service",
    b"CAPIVARA_MATERIALIZER_UNIT_TEMPLATE": b"dsm-hybrid-agent-materialize@{instance_id}.service",
    b"CAPIVARA_NATIVE_COMMAND_UNIT_TEMPLATE": b"dsm-hybrid-agent-native-command@{command_id}.service",
}
_PINNED_MUTATORS = (
    "dashboard/workers/worker.sh",
    "dashboard/workers/hybrid_agent_worker.py",
    "dashboard/workers/hybrid_customer_workspace_worker.py",
    "dashboard/workers/maintenance_hold_gate.py",
    "dashboard/game_uptime_controller_mutation_gate.py",
    "dashboard/game_uptime_controller_agent_http_flock.py",
    "agents/linux/runtime/adapters/systemd.py",
    "agents/linux/runtime/materializers/systemd.py",
    "agents/linux/runtime/backup_client.py",
    "agents/linux/runtime/dayz_operation_client.py",
    "agents/linux/runtime/privileged_materialization.py",
    "agents/linux/runtime/privileged_firewall.py",
    "agents/linux/runtime/game_uptime_finalization_flock.py",
    "agents/linux/runtime/game_uptime_privileged_flock.py",
    "agents/linux/runtime/game_uptime_privileged_admission.py",
    "agents/linux/runtime/game_uptime_maintenance_hold.py",
    "systemd/controller-service-topology.sh",
    *("agents/linux/privileged/" + script for script in _HYBRID_HELPERS.values()),
)


def _systemd_read(*arguments):
    raw = subprocess.run(
        ("/usr/bin/systemctl", *arguments), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "SYSTEMD_COLORS": "0"},
        text=True, timeout=5,
    ).stdout
    if len(raw) > 262144:
        raise LocalScopeLeaseBlocked("installed_mutator_observation_too_large")
    return raw


def _mutator_bytes(path, *, owner=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_mode & 0o022 or not 0 < before.st_size <= 1048576
                or (owner is not None and before.st_uid != owner)):
            raise LocalScopeLeaseBlocked("untrusted_installed_mutator:" + path.name)
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(1048577)
        fingerprint = lambda item: (item.st_dev, item.st_ino, item.st_mode,
                                    item.st_uid, item.st_size, item.st_ctime_ns)
        if (len(content) != before.st_size
                or fingerprint(before) != fingerprint(os.fstat(fd))
                or fingerprint(before) != fingerprint(path.lstat())):
            raise LocalScopeLeaseBlocked("installed_mutator_changed:" + path.name)
        return content, before.st_ctime_ns
    finally:
        os.close(fd)


def _effective_mutator_unit(unit, fragment, expected, *, systemctl):
    raw = systemctl("show", unit, "--no-pager",
                    "--property=LoadState,FragmentPath,DropInPaths,NeedDaemonReload,KillMode")
    required = {"LoadState=loaded", "FragmentPath=" + str(fragment),
                "DropInPaths=", "NeedDaemonReload=no", "KillMode=control-group"}
    if len(raw.splitlines()) != len(required) or set(raw.splitlines()) != required:
        raise LocalScopeLeaseBlocked("installed_mutator_unit_unverified:" + unit)
    if _mutator_bytes(fragment, owner=0)[0] != expected:
        raise LocalScopeLeaseBlocked("installed_mutator_unit_changed:" + unit)


def _check_hybrid_helper_selectors(pid):
    with (Path("/proc") / str(pid) / "environ").open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144 or not raw.endswith(b"\x00"):
        raise LocalScopeLeaseBlocked("installed_hybrid_environment_unverified")
    seen = set()
    for entry in raw[:-1].split(b"\x00"):
        key, _, value = entry.partition(b"=")
        if key.startswith(b"CAPIVARA_") and key.endswith(b"_UNIT_TEMPLATE"):
            if key in seen or value != _HYBRID_HELPER_SELECTORS.get(key):
                raise LocalScopeLeaseBlocked("uncovered_installed_hybrid_helper_selector")
            seen.add(key)


def _check_hybrid_mutators(installed, snapshot, units, *, systemctl, identity):
    status = identity._systemd_status("dsm-dashboard-worker.service")
    account = status.get("User", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", account) or account == "root":
        raise LocalScopeLeaseBlocked("installed_hybrid_worker_account_unverified")
    worker_before = identity._workers_identity()
    if worker_before.get("all_nine_workers_verified") is not True:
        raise LocalScopeLeaseBlocked("installed_hybrid_worker_processes_unverified")

    latest_source_change = 0
    for relative in _PINNED_MUTATORS:
        expected, _ = _mutator_bytes(snapshot / relative, owner=0)
        installed_bytes, changed_at = _mutator_bytes(installed / relative)
        if installed_bytes != expected:
            raise LocalScopeLeaseBlocked("installed_mutator_source_changed:" + relative)
        latest_source_change = max(latest_source_change, changed_at)
    # /proc start ticks establish that the long-lived Hybrid Python processes
    # were forked after the verified source was installed. btime is rounded
    # down, so a same-second replacement is refused.
    boot_rows = [line.split()[1] for line in Path("/proc/stat").read_text().splitlines()
                 if line.startswith("btime ")]
    if len(boot_rows) != 1 or not boot_rows[0].isdecimal():
        raise LocalScopeLeaseBlocked("installed_hybrid_boot_time_unverified")
    boot_ns = int(boot_rows[0]) * 10**9
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    for name in ("hybrid_agent_worker", "hybrid_customer_workspace_worker"):
        worker = worker_before["worker_identities"][name]
        start_ns = boot_ns + worker["start_ticks"] * 10**9 // ticks_per_second
        if start_ns <= latest_source_change:
            raise LocalScopeLeaseBlocked("installed_hybrid_worker_predates_mutator_source:" + name)
        _check_hybrid_helper_selectors(worker["pid"])

    known = {f"dsm-hybrid-agent-{kind}@.service" for kind in _HYBRID_HELPERS}
    listing = systemctl("list-unit-files", "--no-legend", "--no-pager",
                        "dsm-hybrid-agent-*", "capivara-agent*")
    entries = [line.split() for line in listing.splitlines() if line.strip()]
    if any(len(row) < 2 or row[0] not in known for row in entries):
        raise LocalScopeLeaseBlocked("uncovered_installed_mutator_unit")
    if {row[0] for row in entries} != known:
        raise LocalScopeLeaseBlocked("installed_hybrid_helper_inventory_incomplete")
    for name in sorted(known):
        expected, _ = _mutator_bytes(snapshot / "systemd" / (name + ".in"), owner=0)
        expected = expected.replace(b"@DSM_ROOT@", os.fsencode(installed))
        expected = expected.replace(b"@DSM_USER@", account.encode("ascii"))
        _effective_mutator_unit(name.replace("@.", "@dsm928-probe."), units / name,
                                expected, systemctl=systemctl)
    topology = "dsm-controller-service-topology.service"
    expected, _ = _mutator_bytes(snapshot / "systemd" / topology, owner=0)
    _effective_mutator_unit(topology, units / topology, expected, systemctl=systemctl)
    if identity._workers_identity() != worker_before:
        raise LocalScopeLeaseBlocked("installed_hybrid_worker_identity_changed")


def observe_managed_mutator_coverage():
    """Verify the installed paths; observations alone do not retain admission."""
    try:
        _check_controller_topology_settled()
        snapshot = Path(__file__).resolve().parents[1]
        path = snapshot / "update-manager/game-uptime-live-daemon-identity.py"
        loader = SourceFileLoader("dsm928_mutator_worker_identity", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        identity = importlib.util.module_from_spec(spec)
        loader.exec_module(identity)
        _check_hybrid_mutators(Path("/opt/dsm"), snapshot, Path("/etc/systemd/system"),
                               systemctl=_systemd_read, identity=identity)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError,
            subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, LocalScopeLeaseBlocked) else type(exc).__name__
        return ("installed_systemd_mutation_callers_unverified", reason)
    return ()


@contextmanager
def retain_installed_host_scope(
    *, transaction_id: str, release_sha256: str,
    issued_at: int, expires_at: int, expected_agent_ids: list[str],
    local_hybrid_agent_id: str, expected_controller_uid: int,
    expected_worker_uid: int, recover_existing: bool = False,
    operator_reviewed: bool = False,
) -> Iterator[dict]:
    """Retain the installed host fences without opening sessions to Agents."""
    if (os.geteuid() != 0 or type(recover_existing) is not bool
            or operator_reviewed is not True):
        raise LocalScopeLeaseBlocked("root_reviewed_host_scope_required")
    runtime = str(_runtime_dir(True))
    sys.path.insert(0, runtime)
    try:
        from game_uptime_ssh_transport import _root_directory, _root_file, TRUST_DIR, LOCAL_ID
        from game_uptime_hold_coordinator import (
            _installed_game_snapshot, _retain_installed_game_witness,
            _check_installed_systemd_work, _terminal_decision,
            _persist_terminal_receipt,
        )
        if (type(expected_agent_ids) is not list or not 1 <= len(expected_agent_ids) <= 64
                or any(type(item) is not str
                       or not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", item)
                       for item in expected_agent_ids)
                or len(set(expected_agent_ids)) != len(expected_agent_ids)
                or type(local_hybrid_agent_id) is not str
                or local_hybrid_agent_id not in expected_agent_ids):
            raise LocalScopeLeaseBlocked("invalid_complete_operational_inventory")
        for folder in (Path("/etc"), TRUST_DIR):
            _root_directory(folder)
        if _root_file(LOCAL_ID, 192) != (local_hybrid_agent_id + "\n").encode("ascii"):
            raise LocalScopeLeaseBlocked("pinned_local_hybrid_identity_mismatch")
        if expected_worker_uid != expected_controller_uid:
            raise LocalScopeLeaseBlocked("installed_controller_worker_account_mismatch")
        initial_inventory = _read_installed_controller_agents(
            expected_agent_ids, local_hybrid_agent_id,
            expected_uid=expected_controller_uid)
        options = dict(
            transaction_id=transaction_id, release_sha256=release_sha256,
            expected_controller_uid=expected_controller_uid,
            expected_worker_uid=expected_worker_uid,
            shared_lease_window=(issued_at, expires_at),
        )
        if recover_existing:
            options.update(inspect_existing_prepared=True,
                           expected_recovery_agent_ids=[local_hybrid_agent_id])
        else:
            options.update(prepare_fresh_installed=True,
                           expected_installed_agent_ids=[local_hybrid_agent_id])
        witness_path = PENDING_PATH.parent / ("daemon-witness-" + transaction_id + ".json")
        daemon_payload = _daemon_witness_payload({
            "transaction_id": transaction_id, "release_sha256": release_sha256,
            "issued_at": issued_at, "expires_at": expires_at,
            "expected_agent_ids": sorted(expected_agent_ids),
            "local_hybrid_agent_id": local_hybrid_agent_id,
            "controller_uid": expected_controller_uid,
        }, initial_inventory)
        restart_paths = tuple(PENDING_PATH.parent /
                              ("daemon-restart-" + transaction_id + "-" + str(n) + ".json")
                              for n in (1, 2))
        witness_scope = {key: value for key, value in daemon_payload.items()
                         if key not in ("kind", "schema_version", "inventory_sha256",
                                        "live_no_drain_authorized")}

        def read_restart_evidence():
            present = tuple(os.path.lexists(path) for path in restart_paths)
            if present == (False, True):
                raise LocalScopeLeaseBlocked("restart_receipt_sequence_gap")
            return tuple(_root_file(path, 32768)
                         for path, exists in zip(restart_paths, present) if exists)

        def verify_restart_intents(receipts):
            # A failed systemctl invocation can leave the original daemon
            # inventory unchanged even though restart intent is durable.
            # Treat that state as uncertain at every ordinary checkpoint,
            # not merely when reopening the recovery session.
            for sequence in (1, 2):
                intent = PENDING_PATH.parent / (
                    "daemon-restart-intent-" + transaction_id + "-" + str(sequence) + ".json")
                exists = os.path.lexists(intent)
                if sequence > len(receipts):
                    if exists:
                        raise LocalScopeLeaseBlocked("unfinished_restart_intent_requires_manual_review")
                    continue
                if not exists:
                    raise LocalScopeLeaseBlocked("restart_receipt_without_intent")
                receipt = json.loads(receipts[sequence - 1])
                if type(receipt) is not dict:
                    raise LocalScopeLeaseBlocked("invalid_restart_receipt_chain")
                _check_daemon_witness(_root_file(intent, 32768), {
                    "kind": "DSM928DaemonRestartIntent", "schema_version": 1,
                    "transaction_id": transaction_id, "release_sha256": release_sha256,
                    "sequence": sequence,
                    "before_inventory_sha256": receipt.get("before_inventory_sha256"),
                    "live_no_drain_authorized": False,
                })

        recovery_evidence = read_restart_evidence()
        verify_restart_intents(recovery_evidence)
        original_evidence = None
        if recover_existing:
            original_evidence = _root_file(witness_path, 32768)
            if recovery_evidence:
                _validate_restart_receipt_chain(
                    original_evidence, recovery_evidence, witness_scope, initial_inventory)
            else:
                _check_daemon_witness(original_evidence, daemon_payload)
        elif os.path.lexists(witness_path) or recovery_evidence:
            raise LocalScopeLeaseBlocked("existing_daemon_inventory_witness_requires_review")

        def daemon_checkpoint():
            if _read_installed_controller_agents(
                    expected_agent_ids, local_hybrid_agent_id,
                    expected_uid=expected_controller_uid) != initial_inventory:
                raise LocalScopeLeaseBlocked("controller_agent_inventory_changed")
            raw = _root_file(witness_path, 32768)
            receipts = read_restart_evidence()
            if receipts != recovery_evidence:
                raise LocalScopeLeaseBlocked("restart_evidence_changed_during_scope")
            verify_restart_intents(receipts)
            if original_evidence is not None and raw != original_evidence:
                raise LocalScopeLeaseBlocked("original_daemon_inventory_witness_changed")
            if receipts:
                _validate_restart_receipt_chain(raw, receipts, witness_scope, initial_inventory)
            else:
                _check_daemon_witness(raw, daemon_payload)

        _check_controller_topology_settled()
        _check_installed_systemd_work()
        initial_games = _installed_game_snapshot()
        if not recover_existing:
            def before_prepare():
                if observe_managed_mutator_coverage():
                    raise LocalScopeLeaseBlocked("managed_local_mutator_coverage_unverified")
                _check_controller_topology_settled()
                _check_installed_systemd_work()
                if _installed_game_snapshot() != initial_games:
                    raise LocalScopeLeaseBlocked("game_inventory_changed_before_preparation")
                if _read_installed_controller_agents(
                        expected_agent_ids, local_hybrid_agent_id,
                        expected_uid=expected_controller_uid) != initial_inventory:
                    raise LocalScopeLeaseBlocked("controller_inventory_changed_before_preparation")

            options["before_prepare"] = before_prepare
        with retain_local_scopes(**options) as local:
            local["checkpoint"]()
            if not recover_existing:
                if os.path.lexists(witness_path):
                    raise LocalScopeLeaseBlocked("existing_daemon_inventory_witness_requires_review")
                if _read_installed_controller_agents(
                        expected_agent_ids, local_hybrid_agent_id,
                        expected_uid=expected_controller_uid) != initial_inventory:
                    raise LocalScopeLeaseBlocked("controller_agent_inventory_changed_before_binding")
                _persist_terminal_receipt(witness_path, daemon_payload, 0)
                original_evidence = _root_file(witness_path, 32768)
                _check_daemon_witness(original_evidence, daemon_payload)
            daemon_checkpoint()
            game_checkpoint = _retain_installed_game_witness(
                pending=PENDING_PATH, transaction_id=transaction_id,
                release_sha256=release_sha256, agent_id=local_hybrid_agent_id,
                recover_existing=recover_existing, initial=initial_games)
            def retained_fence_checkpoint():
                # Independent of the Controller/Worker process witness.
                # This is not an admission or a complete checkpoint.
                local["checkpoint"]()
                game_checkpoint()
                local["checkpoint"]()

            def checkpoint():
                retained_fence_checkpoint()
                _check_controller_topology_settled()
                _check_installed_systemd_work()
                daemon_checkpoint()
                if observe_managed_mutator_coverage():
                    raise LocalScopeLeaseBlocked("managed_local_mutator_coverage_unverified")
                retained_fence_checkpoint()
            def record_observed_restart():
                """Record a replacement under retained fences; never initiate it.

                This is an internal evidence operation, not restart admission.
                A failed or partial replacement leaves the scope blocked.
                """
                nonlocal initial_inventory, recovery_evidence, original_evidence
                retained_fence_checkpoint()
                _check_installed_systemd_work()
                raw = _root_file(witness_path, 32768)
                if raw != original_evidence:
                    raise LocalScopeLeaseBlocked("original_daemon_inventory_witness_changed")
                sequence = len(recovery_evidence) + 1
                intent = PENDING_PATH.parent / (
                    "daemon-restart-intent-" + transaction_id + "-" + str(sequence) + ".json")
                expected_intent = {"kind": "DSM928DaemonRestartIntent", "schema_version": 1,
                                   "transaction_id": transaction_id, "release_sha256": release_sha256,
                                   "sequence": sequence,
                                   "before_inventory_sha256": hashlib.sha256(
                                       json.dumps(initial_inventory, sort_keys=True,
                                                  separators=(",", ":")).encode()).hexdigest(),
                                   "live_no_drain_authorized": False}
                _check_daemon_witness(_root_file(intent, 32768), expected_intent)
                if read_restart_evidence() != recovery_evidence:
                    raise LocalScopeLeaseBlocked("restart_evidence_changed_during_scope")
                if recovery_evidence:
                    if raw != original_evidence:
                        raise LocalScopeLeaseBlocked("original_daemon_inventory_witness_changed")
                    _validate_restart_receipt_chain(
                        raw, recovery_evidence, witness_scope, initial_inventory)
                else:
                    _check_daemon_witness(raw, daemon_payload)
                if len(recovery_evidence) >= 2:
                    raise LocalScopeLeaseBlocked("restart_transition_limit_reached")
                after = _read_installed_controller_agents(
                    expected_agent_ids, local_hybrid_agent_id,
                    expected_uid=expected_controller_uid)
                _persist_restart_transition(
                    witness_scope, initial_inventory, after,
                    sequence=len(recovery_evidence) + 1,
                    root_file=_root_file, persist_receipt=_persist_terminal_receipt,
                    fence_checkpoint=retained_fence_checkpoint)
                receipts = read_restart_evidence()
                if len(receipts) != len(recovery_evidence) + 1 or receipts[:-1] != recovery_evidence:
                    raise LocalScopeLeaseBlocked("restart_evidence_changed_during_scope")
                _validate_restart_receipt_chain(raw, receipts, witness_scope, after)
                original_evidence = raw
                recovery_evidence = receipts
                initial_inventory = after
                checkpoint()
                return {"status": "restart_transition_recorded",
                        "sequence": len(receipts), "live_no_drain_authorized": False}

            def restart_control_plane():
                """Fixed restart operation, gated by positive retained admission."""
                if (scope_result.get("all_mutators_fenced") is not True
                        or scope_result.get("external_jobs_acked") is not True
                        or observe_managed_mutator_coverage()):
                    raise LocalScopeLeaseBlocked("retained_operational_guarantees_missing")
                checkpoint()
                if len(recovery_evidence) >= 2:
                    raise LocalScopeLeaseBlocked("restart_transition_limit_reached")
                retained_fence_checkpoint()
                sequence = len(recovery_evidence) + 1
                intent = PENDING_PATH.parent / (
                    "daemon-restart-intent-" + transaction_id + "-" + str(sequence) + ".json")
                if os.path.lexists(intent):
                    raise LocalScopeLeaseBlocked("existing_restart_intent_requires_review")
                payload = {"kind": "DSM928DaemonRestartIntent", "schema_version": 1,
                           "transaction_id": transaction_id, "release_sha256": release_sha256,
                           "sequence": sequence,
                           "before_inventory_sha256": hashlib.sha256(
                               json.dumps(initial_inventory, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest(),
                           "live_no_drain_authorized": False}
                _persist_terminal_receipt(intent, payload, 0)
                _check_daemon_witness(_root_file(intent, 32768), payload)
                retained_fence_checkpoint()
                subprocess.run(
                    ["/usr/bin/systemctl", "restart", "dsm-dashboard.service",
                     "dsm-dashboard-worker.service"],
                    check=True, timeout=120, stdin=subprocess.DEVNULL)
                retained_fence_checkpoint()
                return record_observed_restart()

            released = False

            def restart_receipt_count():
                checkpoint()
                return len(recovery_evidence)

            def finalize_terminal(journal_sha256):
                """Internal finalization only, never an update admission.

                The installed transaction owner must durably write the exact
                terminal journal under the fixed recovery workspace first.
                The coordinator cannot turn a fixture or caller-provided
                outcome into an installed terminal decision.
                """
                nonlocal released
                if not recover_existing or released or type(journal_sha256) is not str or not _SHA.fullmatch(journal_sha256):
                    raise LocalScopeLeaseBlocked("reviewed_installed_terminal_journal_required")
                workspace = PENDING_PATH.parent / ("transaction-" + transaction_id)
                _safe_directory(workspace, owner=0)
                if stat.S_IMODE(workspace.lstat().st_mode) != 0o700:
                    raise LocalScopeLeaseBlocked("installed_terminal_workspace_not_private")
                raw = _root_file(workspace / "game-uptime-transaction.json", 65536)
                if hashlib.sha256(raw).hexdigest() != journal_sha256:
                    raise LocalScopeLeaseBlocked("installed_terminal_journal_digest_mismatch")
                report = json.loads(raw)
                scope = {"transaction_id": transaction_id, "release_sha256": release_sha256,
                         "issued_at": issued_at, "expires_at": expires_at,
                         "expected_agent_ids": sorted(expected_agent_ids)}
                if (type(report) is not dict
                        or report.get("kind") != "DSM928InstalledUptimeTransaction"
                        or report.get("schema_version") != 2
                        or report.get("scope") != scope
                        or report.get("local_hybrid_agent_id") != local_hybrid_agent_id
                        or report.get("live_no_drain_authorized") is not False):
                    raise LocalScopeLeaseBlocked("installed_terminal_journal_scope_mismatch")
                decision = _terminal_decision(report.get("status"), journal_sha256)
                checkpoint()
                result = local["release_host"](decision, checkpoint)
                if result.get("installed_hold_released") is not True:
                    raise LocalScopeLeaseBlocked("installed_local_release_incomplete")
                released = True
                return {"status": "installed_terminal_holds_released",
                            "live_no_drain_authorized": False}

            checkpoint()
            # checkpoint verified managed callers while every local lock is
            # retained and independently rejected queued jobs and cron work.
            coverage = observe_managed_mutator_coverage()
            scope_result = {"kind": "DSM928InstalledHostScope",
                   "transaction_id": transaction_id,
                   "release_sha256": release_sha256,
                   "issued_at": issued_at, "expires_at": expires_at,
                   "agent_ids": sorted(expected_agent_ids),
                   "local_hybrid_agent_id": local_hybrid_agent_id,
                   "controller_registry_inventory_matched": True,
                   "known_database_job_queues_terminal": True,
                   "checkpoint": checkpoint,
                   "managed_mutator_blockers": observe_managed_mutator_coverage,
                   "finalize_terminal": finalize_terminal,
                   "restart_control_plane": restart_control_plane,
                   "restart_receipt_count": restart_receipt_count,
                   "all_mutators_fenced": not coverage,
                   "external_jobs_acked": not coverage,
                   "live_no_drain_authorized": False}
            yield dict(scope_result)
            if not released:
                checkpoint()
    finally:
        sys.path.remove(runtime)
