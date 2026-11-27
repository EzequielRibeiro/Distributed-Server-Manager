#!/usr/bin/env python3
"""Experimental *disposable-only* uptime transaction checkpoint for #928.

Not wired to update.sh, not a production update mechanism, and never grants
live_no_drain_authorized. The caller supplies isolated apply/rollback callbacks
and snapshot inspection for disposable units; this module maintains a durable
fail-closed journal and verifies PID/start identity around both operations.
"""
from __future__ import annotations

import json
import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
import fcntl
from functools import wraps
import os
from pathlib import Path
import re
import stat
import tempfile
import sys
from contextlib import ExitStack
from typing import Callable, Mapping

_UNIT = re.compile(r"dsm928-e2e-[a-z0-9-]+\.service\Z")


class TransactionSafetyError(RuntimeError):
    pass


def _workspace(parent: Path) -> Path:
    root = Path(parent)
    if root.is_symlink() or not root.is_dir():
        raise TransactionSafetyError("disposable workspace must be an existing non-symlink directory")
    resolved = root.resolve(strict=True)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved == temp_root or temp_root not in resolved.parents:
        raise TransactionSafetyError("disposable transaction must run inside a temporary sandbox")
    # The fsynced rollback journal contains process identities and is trusted
    # for manual crash recovery. Never accept group/other writable or readable
    # journal directories, even when they are beneath /tmp. The disposable
    # operator must own the directory, so other host users cannot replace it.
    identity = resolved.stat()
    if identity.st_uid != os.geteuid() or identity.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise TransactionSafetyError("disposable journal directory must be private and owned")
    return resolved


def _exclusive_transaction(func):
    """Serialize apply and recovery on the same private workspace inode.

    Lock the directory itself rather than a replaceable journal file.
    Kernel releases the descriptor on process death; the durable journal
    still determines whether a new transaction or recovery is allowed.
    No additional lock file or production path is introduced.
    """
    @wraps(func)
    def guarded(workspace: Path, *args, **kwargs):
        root = _workspace(workspace)
        fd = None
        try:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY |
                         os.O_NOFOLLOW | os.O_CLOEXEC)
            named, held = root.lstat(), os.fstat(fd)
            if ((named.st_dev, named.st_ino) != (held.st_dev, held.st_ino)
                    or not stat.S_ISDIR(held.st_mode)
                    or held.st_uid != os.geteuid()
                    or held.st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
                raise TransactionSafetyError("transaction workspace identity changed")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise TransactionSafetyError("transaction or recovery already in progress") from exc
            # All bound operations acquire the same workspace lock before
            # acquiring the existing local scope. No unbound caller can
            # resume a journal that was created under a bound scope.
            if "_scope" in kwargs:
                raise TransactionSafetyError("caller-supplied scope witness forbidden")
            options = kwargs.pop("local_scope_kwargs", None)
            distributed = kwargs.pop("distributed_fixture_openers", None)
            hybrid_id = kwargs.pop("local_fixture_agent_id", None)
            file_workspace = kwargs.pop("file_transaction_workspace", None)
            file_paths = kwargs.pop("file_transaction_paths", None)
            product_identity = kwargs.pop("file_transaction_identity", None)
            if file_workspace is not None:
                if options is None or distributed is None:
                    raise TransactionSafetyError("fixed product files require retained distributed scope")
                if "apply" in kwargs or "rollback" in kwargs:
                    raise TransactionSafetyError("fixed product files forbid caller mutation callbacks")
                if (func.__name__ == "execute") != (file_paths is not None):
                    raise TransactionSafetyError("fixed product plan is supplied only for fresh apply")
            elif file_paths is not None or product_identity is not None:
                raise TransactionSafetyError("fixed product workspace required")
            finalize = kwargs.pop("finalize_fixture", False)
            if type(finalize) is not bool or (finalize and func.__name__ != "confirm_terminal"):
                raise TransactionSafetyError("fixture finalization requires reviewed terminal confirmation")
            if hybrid_id is not None and (options is None or distributed is None):
                raise TransactionSafetyError("Hybrid partition requires both local and remote scopes")
            if func.__name__ == "confirm_terminal" and (options is None or distributed is None):
                raise TransactionSafetyError("terminal confirmation requires complete retained scopes")
            if options is None:
                if distributed is not None:
                    raise TransactionSafetyError("distributed scope requires local scope")
                return func(root, *args, **kwargs)
            recovery = func.__name__ in ("recover_interrupted", "confirm_terminal")
            if not recovery and os.path.lexists(root / "game-uptime-transaction.json"):
                raise TransactionSafetyError("existing transaction evidence requires manual review")
            if recovery and kwargs.get("operator_reviewed") is not True:
                raise TransactionSafetyError("explicit operator review is required")
            # Validate the complete local/remote partition BEFORE any fresh
            # hold can be written. Do not infer remote membership from the
            # channels which happen to be available at execution time.
            remote_ids = None
            if distributed is not None:
                if not isinstance(options, Mapping):
                    raise TransactionSafetyError("invalid disposable transaction scope")
                ids = options.get("expected_recovery_agent_ids" if recovery
                                  else "expected_fixture_agent_ids")
                remote_ids = _distributed_partition(ids, hybrid_id, distributed)
            transaction_error = None
            try:
                with ExitStack() as stack:
                    lease = stack.enter_context(_bound_local_scope(options, recovery=recovery))
                    receipt = _scope_receipt(lease, options, recovery=recovery)
                    if distributed is not None:
                        remote = stack.enter_context(_bound_distributed_fixture(
                            receipt, options, distributed, remote_ids=remote_ids,
                            hybrid_id=hybrid_id, recovery=recovery))
                        local_checkpoint = receipt["checkpoint"]
                        def combined_checkpoint():
                            local_checkpoint()
                            remote["checkpoint"]()
                            local_checkpoint()
                        receipt["checkpoint"] = combined_checkpoint
                        receipt["distributed_scope_binding"] = {
                            "agent_ids": list(remote["prepared_agent_ids"]),
                            "issued_at": remote["issued_at"],
                            "expires_at": remote["expires_at"],
                            "scope": "disposable_cooperating_agent_sessions_only",
                        }
                        if hybrid_id is not None:
                            receipt["distributed_scope_binding"]["local_hybrid_agent_id"] = hybrid_id
                        combined_checkpoint()
                    file_owner = None
                    if file_workspace is not None:
                        file_root = _workspace(Path(file_workspace))
                        if file_root == root or file_root.parent != root.parent:
                            raise TransactionSafetyError("independent sibling product workspace required")
                        loader = SourceFileLoader(
                            "dsm928_fixed_product_file_owner",
                            str(Path(__file__).with_name("game-uptime-file-transaction.py")))
                        spec = importlib.util.spec_from_loader(loader.name, loader)
                        module = importlib.util.module_from_spec(spec)
                        loader.exec_module(module)
                        file_owner = module.FileTransaction(
                            file_root, file_root / "installed", file_root / "new-payload",
                            transaction_id=receipt["transaction_id"],
                            release_sha256=receipt["release_sha256"],
                            checkpoint=receipt["checkpoint"],
                            product_identity=product_identity)
                        if not recovery:
                            file_owner.prepare(file_paths)
                        identity = file_root.stat()
                        receipt["product_file_binding"] = {
                            "workspace": str(file_root), "device": identity.st_dev,
                            "inode": identity.st_ino,
                            "journal_sha256": file_owner.journal_digest(),
                        }
                        if func.__name__ == "execute":
                            kwargs.update(apply=file_owner.apply, rollback=file_owner.rollback)
                        elif func.__name__ == "recover_interrupted":
                            kwargs["rollback"] = file_owner.rollback
                    def record_terminal_if_present():
                        if distributed is None:
                            return
                        journal = root / "game-uptime-transaction.json"
                        if not journal.is_file() or journal.is_symlink():
                            return
                        raw = journal.read_bytes()
                        result = json.loads(raw)
                        outcome = result.get("status")
                        if outcome not in ("verified", "rolled_back", "recovered_rollback"):
                            return
                        combined_checkpoint()
                        if file_owner is not None:
                            file_owner.verify_terminal(outcome)
                            if file_owner.journal_digest() != receipt["product_file_binding"]["journal_sha256"]:
                                raise TransactionSafetyError("durable product file journal changed")
                        decision = remote["record_terminal"](
                            outcome, hashlib.sha256(raw).hexdigest())
                        if (decision.get("recorded_agent_ids") != remote_ids
                                or decision.get("pending_evidence_retained") is not True):
                            raise TransactionSafetyError("distributed terminal decision incomplete")
                        combined_checkpoint()
                        # Persist the complete confirmation AFTER every Agent
                        # recorded the same terminal digest. A failed write or
                        # interrupted exchange leaves all pending holds intact.
                        runtime = str(Path(__file__).resolve().parents[1] / "agents/linux/runtime")
                        sys.path.insert(0, runtime)
                        try:
                            from game_uptime_hold_coordinator import _persist_terminal_receipt
                        finally:
                            sys.path.remove(runtime)
                        _persist_terminal_receipt(
                            root / "game-uptime-terminal-confirmation.json",
                            {"kind": "DSM928DistributedTerminalConfirmation",
                             "schema_version": 1, "local_scope_binding": _scope_binding(receipt),
                             "outcome": outcome, "journal_sha256": hashlib.sha256(raw).hexdigest(),
                             "recorded_agent_ids": remote_ids,
                             "pending_evidence_retained": True,
                             "live_no_drain_authorized": False}, os.geteuid())
                        combined_checkpoint()
                        if finalize:
                            confirmation = root / "game-uptime-terminal-confirmation.json"
                            confirmation_sha = hashlib.sha256(confirmation.read_bytes()).hexdigest()
                            released = remote["release_fixture"](
                                outcome, decision["journal_sha256"], confirmation_sha)
                            if released.get("released_agent_ids") != remote_ids:
                                raise TransactionSafetyError("distributed fixture release incomplete")
                            # The remote sessions have finished; only the local
                            # retained checkpoint is meaningful from here.
                            local_checkpoint()
                            result = lease["release_fixture"](
                                outcome, decision["journal_sha256"], confirmation_sha)
                            if result.get("fixture_hold_released") is not True:
                                raise TransactionSafetyError("local fixture release incomplete")
                            _persist_terminal_receipt(
                                root / "game-uptime-fixture-release.json",
                                {"kind": "DSM928FixtureRelease", "schema_version": 1,
                                 "confirmation_sha256": confirmation_sha,
                                 "released_agent_ids": receipt["agent_ids"],
                                 "live_no_drain_authorized": False}, os.geteuid())

                    try:
                        result = func(root, *args, **kwargs, _scope=receipt)
                    except TransactionSafetyError as exc:
                        # Context managers may translate an exception raised
                        # at yield into a scope error. Keep the exact rejected
                        # transaction diagnosis, not a generic lease error.
                        transaction_error = exc
                        # A completed rollback is terminal; do not perform
                        # another rollback when remote confirmation fails.
                        if distributed is not None and str(exc) == "transaction rejected and rollback completed":
                            record_terminal_if_present()
                        raise
                    record_terminal_if_present()
                    if finalize:
                        result = {**result, "fixture_hold_released": True}
                    return result
            except TransactionSafetyError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                cause = exc
                while cause is not None:
                    if transaction_error is not None and cause is transaction_error:
                        raise transaction_error
                    cause = cause.__cause__
                raise TransactionSafetyError("transaction local scope blocked") from exc
        finally:
            if fd is not None:
                os.close(fd)
    return guarded


def _bound_local_scope(options: Mapping, *, recovery: bool):
    """Acquire a fixture-only scope from the existing local lease module."""
    if (not isinstance(options, Mapping)
            or options.get("fixture_root") is None
            or options.get("prepare_fresh_fixture") is not (not recovery)
            or options.get("inspect_existing_prepared", False) is not recovery):
        raise TransactionSafetyError("invalid disposable transaction scope")
    ids = options.get("expected_recovery_agent_ids" if recovery
                      else "expected_fixture_agent_ids")
    if not isinstance(ids, list) or not ids:
        raise TransactionSafetyError("transaction scope requires Agent inventory")
    loader = SourceFileLoader("dsm928_tx_bound_local_scope",
                              str(Path(__file__).with_name("game-uptime-local-scope-lease.py")))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.retain_local_scopes(**dict(options))


def _distributed_partition(ids, hybrid_id, openers):
    """Partition an independently pinned full inventory without omissions.

    The Hybrid Agent is covered by the retained local worker/helper locks;
    standalone endpoints are covered by the authenticated session protocol.
    This validates fixture scope only, not installed daemon coverage.
    """
    if (type(ids) is not list or not ids
            or any(type(agent) is not str or
                   not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", agent)
                   for agent in ids)
            or len(set(ids)) != len(ids)):
        raise TransactionSafetyError("invalid full Agent inventory")
    if hybrid_id is not None and (type(hybrid_id) is not str or hybrid_id not in ids):
        raise TransactionSafetyError("Hybrid Agent outside full inventory")
    remote_ids = sorted(agent for agent in ids if agent != hybrid_id)
    if (not remote_ids or type(openers) is not dict
            or set(openers) != set(remote_ids)
            or any(not callable(opener) for opener in openers.values())):
        raise TransactionSafetyError("distributed fixture inventory incomplete")
    return remote_ids


def _bound_distributed_fixture(receipt: Mapping, options: Mapping,
                               openers: Mapping, *, remote_ids: list[str],
                               hybrid_id: str | None, recovery: bool):
    """Compose the actual session protocol with the existing disposable lease.

    Only injected fixture channels are permitted here. The operational SSH
    adapter is intentionally not invoked against real hosts from this test
    transaction. A production updater still requires independent coverage.
    """
    if (os.environ.get("CAPIVARA_DSM928_SYSTEMD_E2E") != "1"
            or os.path.lexists("/opt/dsm")):
        raise TransactionSafetyError("distributed transaction fixture requires isolated systemd host")
    if (not set(remote_ids).issubset(receipt["agent_ids"])
            or set(openers) != set(remote_ids)):
        raise TransactionSafetyError("distributed fixture inventory incomplete")
    receipt["checkpoint"]()
    marker = json.loads(Path(options["hold_path"]).read_bytes())
    receipt["checkpoint"]()
    runtime = str(Path(__file__).resolve().parents[1] / "agents/linux/runtime")
    sys.path.insert(0, runtime)
    try:
        from game_uptime_hold_coordinator import retain_distributed_agent_sessions
    finally:
        sys.path.remove(runtime)
    return retain_distributed_agent_sessions(
        transaction_id=receipt["transaction_id"],
        release_sha256=receipt["release_sha256"],
        issued_at=marker["issued_at"], expires_at=marker["expires_at"],
        expected_agent_ids=receipt["agent_ids"],
        local_hybrid_agent_id=hybrid_id, session_openers=openers,
        recover_existing=recovery, operator_reviewed=recovery)


def _scope_binding(scope: Mapping | None) -> dict | None:
    if scope is None:
        return None
    result = {"transaction_id": scope["transaction_id"],
              "release_sha256": scope["release_sha256"],
              "agent_ids": scope["agent_ids"],
              "evidence_sha256": scope["evidence_sha256"]}
    if "distributed_scope_binding" in scope:
        result["distributed_scope_binding"] = scope["distributed_scope_binding"]
    if "product_file_binding" in scope:
        result["product_file_binding"] = scope["product_file_binding"]
    return result


def _scope_receipt(scope: Mapping, options: Mapping, *, recovery: bool) -> dict:
    """Bind journal to the exact on-disk lease evidence, not just a nonce."""
    if (scope.get("live_no_drain_authorized") is not False
            or scope.get("worker_lock_inodes_exclusively_held") != 9
            or scope.get("controller_http_lock_exclusively_held") is not True
            or not callable(scope.get("checkpoint"))
            or scope.get("existing_prepared_recovery_inspection_only") is not recovery
            or (recovery and scope.get("recovery_scope_inodes_retained") is not True)
            or (not recovery and scope.get("fresh_durable_fixture_evidence") is not True)):
        raise TransactionSafetyError("untrusted local scope witness")
    checkpoint = scope["checkpoint"]
    pending = Path(options["pending_path"])
    evidence = [Path(options["hold_path"]), pending,
                pending.parent / "no-drain-release-binding.json",
                pending.parent / "no-drain-agent-inventory.json"]
    checkpoint()
    digest = hashlib.sha256()
    for path in evidence:
        raw = path.read_bytes()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    checkpoint()
    return {"transaction_id": scope["transaction_id"],
            "release_sha256": scope["release_sha256"],
            "agent_ids": sorted(options["expected_recovery_agent_ids" if recovery
                                        else "expected_fixture_agent_ids"]),
            "evidence_sha256": digest.hexdigest(), "checkpoint": checkpoint}


def _snapshot(name: str, inspect: Callable[[str], Mapping]) -> dict:
    try:
        state = inspect(name)
        if not isinstance(state, Mapping) or state.get("unit") != name:
            raise ValueError("unit identity mismatch")
        pid = state.get("pid")
        started = state.get("started")
        if type(pid) is not int or pid < 2 or type(started) is not int or started <= 0:
            raise ValueError("invalid PID or monotonic start timestamp")
        if state.get("state") != "active":
            raise ValueError("disposable unit not active")
        # The systemd unit witness is optional for older disposable fixtures,
        # but once supplied it becomes part of the durable original identity.
        # An omitted, malformed or changed witness after apply/rollback is
        # rejected as a process-preservation failure even if PID is unchanged.
        result = {"unit": name, "pid": pid, "started": started, "state": "active"}
        witness = state.get("unit_config_sha256")
        if witness is not None:
            if (not isinstance(witness, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", witness)):
                raise ValueError("invalid systemd unit configuration witness")
            result["unit_config_sha256"] = witness
        return result
    except Exception as exc:
        raise TransactionSafetyError(f"cannot prove disposable unit identity: {name}") from exc



def _active_set(units: list[str], list_units: Callable[[], list[str]]) -> None:
    """Verify ALL active disposable game units, not merely the known PIDs."""
    try:
        observed = list_units()
    except Exception as exc:
        raise TransactionSafetyError("complete game inventory unreadable") from exc
    if (not isinstance(observed, list)
            or any(not isinstance(x, str) or not _UNIT.fullmatch(x) for x in observed)
            or len(observed) != len(set(observed))
            or sorted(observed) != sorted(units)):
        raise TransactionSafetyError("complete active game unit set changed")


def attest_handoff(units: list[str], *, inspect: Callable[[str], Mapping],
                   list_units: Callable[[], list[str]]) -> dict:
    """Produce a read-only double-sampled witness for a disposable transaction."""
    if (not isinstance(units, list) or not units
            or any(not isinstance(x, str) or not _UNIT.fullmatch(x) for x in units)
            or len(units) != len(set(units))):
        raise TransactionSafetyError("only disposable E2E game units are allowed")
    _active_set(units, list_units)
    original = [_snapshot(x, inspect) for x in sorted(units)]
    if any("unit_config_sha256" not in x for x in original):
        raise TransactionSafetyError("full systemd unit digest is required")
    _active_set(units, list_units)
    if [_snapshot(x, inspect) for x in sorted(units)] != original:
        raise TransactionSafetyError("game identity changed during handoff")
    return {"kind": "DSM928DisposableInventoryHandoff",
            "scope": "disposable_only_not_production",
            "live_no_drain_authorized": False, "original_units": original}


def _check_handoff(expected: list[dict], handoff: Mapping) -> None:
    if (not isinstance(handoff, Mapping)
            or handoff.get("kind") != "DSM928DisposableInventoryHandoff"
            or handoff.get("scope") != "disposable_only_not_production"
            or handoff.get("live_no_drain_authorized") is not False
            or handoff.get("original_units") != expected
            or any("unit_config_sha256" not in x for x in expected)):
        raise TransactionSafetyError("preflight handoff no longer matches game processes")


def _digest(original: list[dict]) -> str:
    return hashlib.sha256(json.dumps(original, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def _checkpoint(path: Path, status: str, originals: list[dict], detail: str = "",
                strict_inventory: bool = False, scope_binding: dict | None = None) -> None:
    report = {
        "kind": "DSM928DisposableUptimeTransaction",
        "scope": "disposable_only_not_production",
        "status": status,
        "live_no_drain_authorized": False,
        "original_units": originals,
        "original_units_sha256": _digest(originals),
        "strict_inventory": strict_inventory,
        "detail": detail[:300],
    }
    if scope_binding is not None:
        report["local_scope_binding"] = scope_binding
    tmp = path.with_name("." + path.name + ".part")
    # No following a stale staging symlink; never overwrite a previous journal.
    if tmp.exists() or tmp.is_symlink():
        raise TransactionSafetyError("stale transaction journal staging file")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp.exists():
            tmp.unlink()


@_exclusive_transaction
def execute(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    apply: Callable[[], None],
    rollback: Callable[[], None],
    handoff: Mapping | None = None,
    list_units: Callable[[], list[str]] | None = None,
    local_scope_kwargs: Mapping | None = None,
    distributed_fixture_openers: Mapping | None = None,
    local_fixture_agent_id: str | None = None,
    _scope: Mapping | None = None,
) -> dict:
    """Run one isolated transaction. Fail closed after any interrupted run.

    On a caught apply/check failure, attempt rollback and re-verify PIDs.
    On SIGKILL/SystemExit, the nonterminal journal remains; manual recovery
    is required and automatic replay is intentionally prohibited.
    """
    root = _workspace(workspace)
    if (not isinstance(units, list) or not units
            or any(not isinstance(unit, str) or not _UNIT.fullmatch(unit) for unit in units)
            or len(units) != len(set(units))):
        raise TransactionSafetyError("only named disposable E2E systemd units are allowed")
    if (handoff is None) != (list_units is None):
        raise TransactionSafetyError("handoff and complete inventory callback must be paired")
    strict = handoff is not None
    if _scope is not None and not strict:
        raise TransactionSafetyError("bound transaction requires strict game inventory")
    bound = _scope_binding(_scope)
    def scope_checkpoint():
        if _scope is not None:
            _scope["checkpoint"]()
    scope_checkpoint()
    path = root / "game-uptime-transaction.json"
    if path.exists() or path.is_symlink():
        raise TransactionSafetyError("existing transaction evidence requires manual review")
    if strict:
        _active_set(units, list_units)
    before = [_snapshot(x, inspect) for x in sorted(units)]
    if strict:
        _check_handoff(before, handoff)
        _active_set(units, list_units)
    _checkpoint(path, "prepared", before, strict_inventory=strict, scope_binding=bound)
    if strict:
        try:
            _active_set(units, list_units)
            if [_snapshot(x, inspect) for x in sorted(units)] != before:
                raise TransactionSafetyError("process identity changed before apply")
        except TransactionSafetyError as exc:
            _checkpoint(path, "manual_recovery_required", before, str(exc),
                        strict_inventory=True, scope_binding=bound)
            raise TransactionSafetyError("game handoff changed before apply; manual review required") from exc
    try:
        scope_checkpoint()
        apply()
        scope_checkpoint()
        _checkpoint(path, "applied", before, strict_inventory=strict, scope_binding=bound)
        if strict:
            _active_set(units, list_units)
        after = [_snapshot(x["unit"], inspect) for x in before]
        if after != before:
            raise TransactionSafetyError("process or unit configuration changed during apply")
        scope_checkpoint()
        _checkpoint(path, "verified", before, strict_inventory=strict, scope_binding=bound)
        return {"status": "verified", "live_no_drain_authorized": False, "units": after}
    except Exception as exc:
        # Unknown/missing active units after apply must not cause a blind rollback.
        if strict:
            try:
                _active_set(units, list_units)
            except TransactionSafetyError as inventory_exc:
                _checkpoint(path, "manual_recovery_required", before,
                            str(inventory_exc), strict_inventory=True, scope_binding=bound)
                raise TransactionSafetyError(
                    "game inventory changed after apply; manual recovery required") from exc
        try:
            scope_checkpoint()
            rollback()
            scope_checkpoint()
            if strict:
                _active_set(units, list_units)
            after_rollback = [_snapshot(x["unit"], inspect) for x in before]
            if after_rollback != before:
                raise TransactionSafetyError("process or unit configuration changed during rollback")
            scope_checkpoint()
            _checkpoint(path, "rolled_back", before, str(exc), strict_inventory=strict, scope_binding=bound)
        except Exception as rollback_exc:
            _checkpoint(path, "manual_recovery_required", before, str(rollback_exc),
                        strict_inventory=strict, scope_binding=bound)
            raise TransactionSafetyError("rollback failed; manual recovery required") from rollback_exc
        raise TransactionSafetyError("transaction rejected and rollback completed") from exc


@_exclusive_transaction
def recover_interrupted(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    rollback: Callable[[], None],
    operator_reviewed: bool = False,
    list_units: Callable[[], list[str]] | None = None,
    local_scope_kwargs: Mapping | None = None,
    distributed_fixture_openers: Mapping | None = None,
    local_fixture_agent_id: str | None = None,
    _scope: Mapping | None = None,
) -> dict:
    """Explicit, disposable-only rollback of one interrupted transaction.

    Not automatic startup recovery: the operator must review journal and
    externally verify the appropriate rollback callback before opting in.
    A process crash *during* this recovery remains manual-only, not replayed.
    """
    root = _workspace(workspace)
    if operator_reviewed is not True:
        raise TransactionSafetyError("explicit operator review is required")
    if (not isinstance(units, list) or not units
            or any(not isinstance(unit, str) or not _UNIT.fullmatch(unit)
                   for unit in units)
            or len(units) != len(set(units))):
        raise TransactionSafetyError("only named disposable E2E systemd units are allowed")
    path = root / "game-uptime-transaction.json"
    if path.is_symlink() or not path.is_file():
        raise TransactionSafetyError("missing or unsafe transaction journal")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized journal")
        report = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise TransactionSafetyError("unreadable transaction journal") from exc
    if (not isinstance(report, dict)
            or report.get("kind") != "DSM928DisposableUptimeTransaction"
            or report.get("scope") != "disposable_only_not_production"
            or report.get("live_no_drain_authorized") is not False
            or report.get("status") not in {"prepared", "applied"}
            or not isinstance(report.get("original_units"), list)):
        raise TransactionSafetyError("journal does not prove recoverable interruption")
    bound = _scope_binding(_scope)
    if report.get("local_scope_binding") != bound:
        raise TransactionSafetyError("durable local scope binding mismatch")
    def scope_checkpoint():
        if _scope is not None:
            _scope["checkpoint"]()
    scope_checkpoint()
    recorded = report["original_units"]
    if len(recorded) != len(units) or any(not isinstance(x, dict) for x in recorded):
        raise TransactionSafetyError("journal inventory mismatch")
    try:
        matches_digest = report.get("original_units_sha256") == _digest(recorded)
    except (ValueError, TypeError):
        matches_digest = False
    if not matches_digest:
        raise TransactionSafetyError("durable process witness digest mismatch")
    strict = report.get("strict_inventory") is True
    if strict != (list_units is not None):
        raise TransactionSafetyError("durable inventory witness callback missing or unexpected")
    if strict:
        _active_set(units, list_units)
    actual = [_snapshot(x, inspect) for x in sorted(units)]
    if recorded != actual:
        raise TransactionSafetyError(
            "process identity changed or unit configuration changed; manual recovery required")
    if strict:
        _active_set(units, list_units)
    _checkpoint(path, "recovery_started", actual,
                "explicit disposable-only recovery", strict_inventory=strict, scope_binding=bound)
    try:
        if strict:
            _active_set(units, list_units)
        scope_checkpoint()
        rollback()
        scope_checkpoint()
        if strict:
            _active_set(units, list_units)
        after = [_snapshot(name, inspect) for name in sorted(units)]
        if after != actual:
            raise TransactionSafetyError("process or unit configuration changed during recovery rollback")
        scope_checkpoint()
        _checkpoint(path, "recovered_rollback", actual, strict_inventory=strict, scope_binding=bound)
        return {"status": "recovered_rollback",
                "live_no_drain_authorized": False, "units": after}
    except Exception as exc:
        _checkpoint(path, "manual_recovery_required", actual, str(exc),
                    strict_inventory=strict, scope_binding=bound)
        raise TransactionSafetyError("recovery rollback failed; manual review required") from exc



@_exclusive_transaction
def confirm_terminal(
    workspace: Path,
    units: list[str],
    *,
    inspect: Callable[[str], Mapping],
    list_units: Callable[[], list[str]],
    operator_reviewed: bool = False,
    local_scope_kwargs: Mapping | None = None,
    distributed_fixture_openers: Mapping | None = None,
    local_fixture_agent_id: str | None = None,
    finalize_fixture: bool = False,
    _scope: Mapping | None = None,
) -> dict:
    """Retry terminal confirmation without re-executing apply or rollback.

    Requires the exact original durable binding and preserved game identity.
    The enclosing retained-scope owner performs the authenticated exchanges
    and persists the complete confirmation. Never clears pending evidence.
    """
    if operator_reviewed is not True or _scope is None:
        raise TransactionSafetyError("explicit retained terminal review required")
    if (not isinstance(units, list) or not units
            or any(not isinstance(unit, str) or not _UNIT.fullmatch(unit) for unit in units)
            or len(units) != len(set(units))):
        raise TransactionSafetyError("only named disposable E2E systemd units are allowed")
    path = _workspace(workspace) / "game-uptime-transaction.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ValueError("untrusted terminal journal")
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized terminal journal")
        report = json.loads(raw)
    except (OSError, ValueError, TypeError) as exc:
        raise TransactionSafetyError("terminal journal unreadable") from exc
    if (not isinstance(report, dict)
            or report.get("kind") != "DSM928DisposableUptimeTransaction"
            or report.get("scope") != "disposable_only_not_production"
            or report.get("live_no_drain_authorized") is not False
            or report.get("status") not in ("verified", "rolled_back", "recovered_rollback")
            or report.get("strict_inventory") is not True
            or report.get("local_scope_binding") != _scope_binding(_scope)):
        raise TransactionSafetyError("terminal journal scope binding mismatch")
    _scope["checkpoint"]()
    _active_set(units, list_units)
    observed = [_snapshot(unit, inspect) for unit in sorted(units)]
    if (report.get("original_units") != observed
            or report.get("original_units_sha256") != _digest(observed)):
        raise TransactionSafetyError("terminal journal game identity changed")
    _active_set(units, list_units)
    _scope["checkpoint"]()
    return {"status": report["status"], "live_no_drain_authorized": False,
            "terminal_confirmation_retried": True, "units": observed}
