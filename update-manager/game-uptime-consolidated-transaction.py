#!/usr/bin/env python3
"""#928: ONE disposable-only chain for signed release, ACK fence and rollback.

This bridge intentionally cannot be invoked from production update.sh.
It composes existing independently tested security and transaction modules
for a final CI rehearsal. Real publisher enrollment and distributed actor
ACK emission are NOT implemented here; no live no-drain authorization exists.
"""
from __future__ import annotations

import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Callable, Mapping, Any

_TRANSACTION = re.compile(r"[0-9a-f]{32}\Z")
_GAME = re.compile(r"dsm928-e2e-[a-z0-9-]+\.service\Z")


class ConsolidatedTransactionBlocked(RuntimeError):
    pass


def _load(name: str, relative: str):
    path = Path(__file__).with_name(relative)
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _fixture_root(value: Path) -> Path:
    root = Path(value)
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ConsolidatedTransactionBlocked("missing disposable workspace")
    real = root.resolve(strict=True)
    owner = real.stat()
    if (real == temp or temp not in real.parents
            or owner.st_uid != os.geteuid()
            or owner.st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
        raise ConsolidatedTransactionBlocked("unsafe fixture owner or permissions")
    marker = real / "fixture-owner"
    if (marker.is_symlink() or not marker.is_file()
            or marker.read_bytes() != b"DSM928_DISPOSABLE_FIXTURE_V1\n"):
        raise ConsolidatedTransactionBlocked("missing disposable fixture marker")
    return real


def _witness(units: list[str], inspect: Callable, list_units: Callable) -> list[dict]:
    if (not isinstance(units, list) or not units
            or any(type(u) is not str or not _GAME.fullmatch(u) for u in units)
            or len(units) != len(set(units))):
        raise ConsolidatedTransactionBlocked("invalid disposable game names")
    def sample():
        observed = list_units()
        if (type(observed) is not list or len(observed) != len(set(observed))
                or sorted(observed) != sorted(units)):
            raise ConsolidatedTransactionBlocked("active game unit set changed")
        states = []
        for name in sorted(units):
            state = inspect(name)
            if (not isinstance(state, Mapping) or state.get("unit") != name
                    or state.get("state") != "active"
                    or type(state.get("pid")) is not int or state["pid"] < 2
                    or type(state.get("started")) is not int or state["started"] <= 0
                    or not isinstance(state.get("unit_config_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", state["unit_config_sha256"])):
                raise ConsolidatedTransactionBlocked("incomplete live systemd witness")
            states.append(dict(state))
        return states
    first = sample()
    if sample() != first:
        raise ConsolidatedTransactionBlocked("unstable game systemd witness")
    return first


def run_disposable_integrated(
    workspace: Path,
    *,
    archive: Path,
    manifest: Path,
    statement: Path,
    release_signature: Path,
    reviewed_commit: str,
    publisher_public_key: Path,
    expected_publisher_key_sha256: str,
    security_workspace: Path,
    security_approval: Path,
    security_signature: Path,
    security_publisher_public_key: Path,
    security_key_sha256: str,
    transaction_id: str,
    actor_acks: list[dict],
    actor_keys: Mapping[str, bytes],
    units: list[str],
    inspect: Callable,
    list_units: Callable,
    execute_fixture: Callable,
    expected_journal_status: str,
    local_scope_kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One-shot CI-only security→transaction→PID witness, fail-closed.

    The operation passed in is the already-restricted update.sh fixture main
    that performs apply and its internal rollback; this never invokes live
    updater callbacks or changes the production no-drain gate.
    """
    # sudo in the existing systemd workflow drops GITHUB_ACTIONS and
    # RUNNER_ENVIRONMENT. Reuse its stronger, host-visible isolation check:
    # real DSM installation, active Capivara game units or missing opt-in
    # always block before touching the disposable fixture.
    if (os.environ.get("CAPIVARA_DSM928_SYSTEMD_E2E") != "1"
            or os.geteuid() != 0
            or not Path("/run/systemd/system").is_dir()
            or Path("/opt/dsm").exists() or Path("/opt/dsm").is_symlink()):
        raise ConsolidatedTransactionBlocked("not a disposable systemd runner")
    import subprocess
    try:
        active = subprocess.run(
            ("systemctl", "list-units", "--type=service", "--state=active",
             "--all", "--no-legend", "--plain", "capivara-instance-*.service"),
            capture_output=True, text=True, check=False, timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConsolidatedTransactionBlocked("live-game inventory unavailable") from exc
    if active.returncode != 0 or active.stdout.strip():
        raise ConsolidatedTransactionBlocked("refusing DSM host with active games")
    root = _fixture_root(workspace)
    security_root = _fixture_root(security_workspace)
    if security_root == root:
        raise ConsolidatedTransactionBlocked("independent security evidence workspace required")
    if (not isinstance(transaction_id, str)
            or not _TRANSACTION.fullmatch(transaction_id)
            or expected_journal_status not in ("verified", "rolled_back")):
        raise ConsolidatedTransactionBlocked("invalid transaction expectation")
    if (not callable(execute_fixture) or not callable(inspect)
            or not callable(list_units)):
        raise ConsolidatedTransactionBlocked("missing fixed transaction callbacks")
    if ((root / "dsm928-composite-journal").exists()
            or any((root / "backups").glob("*.tar.gz"))):
        raise ConsolidatedTransactionBlocked("existing transaction requires recovery")
    before = _witness(units, inspect, list_units)
    provenance = _load("dsm928_integrated_release_provenance",
                       "game-uptime-release-provenance.py")
    try:
        released = provenance.verify_signed_release(
            archive, manifest, statement, release_signature,
            expected_commit=reviewed_commit,
            trusted_public_key=publisher_public_key,
            disposable_fixture=True,
        )
    except Exception as exc:
        raise ConsolidatedTransactionBlocked("release origin signature not verified") from exc
    pub = Path(publisher_public_key)
    if (pub.is_symlink() or hashlib.sha256(pub.read_bytes()).hexdigest()
            != expected_publisher_key_sha256):
        raise ConsolidatedTransactionBlocked("reviewed publisher key pin mismatch")
    if (released.get("artifact_signature_verified") is not True
            or released.get("scope") != "disposable_fixture_only"
            or released.get("live_no_drain_authorized") is not False):
        raise ConsolidatedTransactionBlocked("unsafe release-origin result")
    sha = released["artifact_sha256"]
    security = _load("dsm928_integrated_disposable_fence",
                     "game-uptime-security-fence.py")
    try:
        secured = security.verify_disposable_fence(
            security_root, archive=archive, release_sha256=sha,
            release_commit=reviewed_commit,
            release_version=json.loads(Path(manifest).read_text())["version"],
            transaction_id=transaction_id, approval_file=security_approval,
            signature_file=security_signature,
            publisher_public_key=security_publisher_public_key,
            trusted_publisher_key_sha256=security_key_sha256,
            acknowledgements=actor_acks, actor_keys=actor_keys,
        )
    except Exception as exc:
        raise ConsolidatedTransactionBlocked("actor quorum or transaction signature rejected") from exc
    if (secured.get("transaction_id") != transaction_id
            or secured.get("release_sha256") != sha
            or secured.get("fixture_actor_quorum_verified") is not True
            or secured.get("live_no_drain_authorized") is not False):
        raise ConsolidatedTransactionBlocked("transaction fence not bound")
    if _witness(units, inspect, list_units) != before:
        raise ConsolidatedTransactionBlocked("game changed before update")
    # The scoped local kernel locks are mandatory for the whole disposable
    # file swap, rollback verification, and PID witness. No test caller may
    # bypass them by running execute_fixture() directly.
    if (not isinstance(local_scope_kwargs, Mapping)
            or local_scope_kwargs.get("transaction_id") != transaction_id
            or local_scope_kwargs.get("release_sha256") != sha):
        raise ConsolidatedTransactionBlocked("transaction-local lock lease missing or unbound")
    scope_module = _load("dsm928_integrated_kernel_scope_lease",
                         "game-uptime-local-scope-lease.py")
    # The signed security-fence receipt is durable before entering the lease.
    # A failed/busy lock leaves it for manual recovery; never auto-retry.
    try:
        with scope_module.retain_local_scopes(**dict(local_scope_kwargs)) as scope:
            if (scope.get("transaction_id") != transaction_id
                    or scope.get("release_sha256") != sha
                    or scope.get("controller_http_lock_exclusively_held") is not True
                    or scope.get("worker_lock_inodes_exclusively_held") != 9
                    or scope.get("all_mutators_fenced") is not False
                    or scope.get("remote_agents_acked") is not False
                    or scope.get("live_no_drain_authorized") is not False):
                raise ConsolidatedTransactionBlocked("untrusted local scope receipt")
            if _witness(units, inspect, list_units) != before:
                raise ConsolidatedTransactionBlocked("game changed under local lease")
            operation = execute_fixture()
            if (not isinstance(getattr(operation, "returncode", None), int)
                    or operation.returncode !=
                    (0 if expected_journal_status == "verified" else 2)):
                raise ConsolidatedTransactionBlocked("disposable update result unexpected")
            journal = root / "dsm928-composite-journal/game-uptime-transaction.json"
            if journal.is_symlink() or not journal.is_file():
                raise ConsolidatedTransactionBlocked("durable rollback journal missing")
            try:
                evidence = json.loads(journal.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ConsolidatedTransactionBlocked("invalid durable update journal") from exc
            if (evidence.get("status") != expected_journal_status
                    or evidence.get("strict_inventory") is not True
                    or evidence.get("live_no_drain_authorized") is not False
                    or len(evidence.get("original_units") or []) < 2):
                raise ConsolidatedTransactionBlocked("disposable rollback outcome not proven")
            if _witness(units, inspect, list_units) != before:
                raise ConsolidatedTransactionBlocked("game identity changed across transaction")
            result = {
                "kind": "DSM928DisposableIntegratedSecurityTransaction",
                "status": "verified_disposable_only",
                "transaction_id": transaction_id,
                "release_sha256": sha,
                "journal_status": expected_journal_status,
                "units_preserved": len(before),
                "fixture_publisher_signed": True,
                "fixture_actor_acks_verified": True,
                "local_controller_lock_held_during_transaction": True,
                "local_worker_lock_count_held_during_transaction": 9,
                "controller_routes_opted_in_verified": False,
                "worker_process_inventory_verified": False,
                "production_publisher_enrolled": False,
                "operational_agents_quiesced": False,
                "live_no_drain_authorized": False,
            }
        # The scope's post-yield hold check and lock release both completed.
        return result
    except scope_module.LocalScopeLeaseBlocked as exc:
        raise ConsolidatedTransactionBlocked("local scope lease unavailable") from exc
