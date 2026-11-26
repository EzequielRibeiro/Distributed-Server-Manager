#!/usr/bin/env python3
"""Installed #928 execution owner. Never drains games or migrates databases.

Both bounded file modes share the retained transaction and recovery owner.
Restart candidates require separate ownership and rollback evidence.
The existing operational review and retained scope still do not attest
all mutators and external jobs; no caller-provided approval booleans.
"""
from __future__ import annotations
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

SNAPSHOT = Path("/usr/local/libexec/capivara-dsm-928-updater")
STATE = Path("/var/lib/capivara-dsm-928")
TARGET = STATE / "reviewed-release/payload"
INSTALLED = Path("/opt/dsm")
TRUST = Path("/etc/capivara-dsm")


class InstalledTransactionBlocked(RuntimeError):
    pass


def _trusted(path, directory=False):
    info = path.lstat()
    if (info.st_uid != 0 or info.st_mode & 0o022
            or (not stat.S_ISDIR(info.st_mode) if directory else
                not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
        raise InstalledTransactionBlocked("untrusted_installed_transaction_input")


def _load(name):
    path = SNAPSHOT / "update-manager" / name
    _trusted(path)
    loader = SourceFileLoader("dsm928_installed_" + name.replace("-", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _version_key(root):
    # Build metadata does not change precedence. Reject malformed or
    # excessively large input rather than delegating to candidate scripts.
    path = root / "version"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 256:
        raise InstalledTransactionBlocked("invalid_release_version_file")
    raw = path.read_text(encoding="ascii").strip()
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", raw)
    if match is None:
        raise InstalledTransactionBlocked("invalid_release_semver")
    prerelease = match.group(4)
    ids = prerelease.split(".") if prerelease is not None else []
    if any(x.isdigit() and len(x) > 1 and x.startswith("0") for x in ids):
        raise InstalledTransactionBlocked("invalid_numeric_prerelease")
    return (tuple(int(x) for x in match.groups()[:3]), prerelease is None,
            tuple((0, int(x)) if x.isdigit() else (1, x) for x in ids))


def _require_forward_version(installed, target):
    if _version_key(target) <= _version_key(installed):
        raise InstalledTransactionBlocked("same_version_or_downgrade_not_allowed")


def _validate_static_plan(report):
    review = report.get("operational_release_review") or {}
    plan = (report.get("release_impact") or {}).get("fixed_file_transaction_plan") or {}
    if (review.get("artifact_origin_verified") is not True
            or review.get("target_tree_bound_to_signed_tar") is not True):
        raise InstalledTransactionBlocked("signed_exact_target_not_verified")
    paths = plan.get("changed_paths")
    if (plan.get("status") != "compatible_file_plan_only"
            or plan.get("bootstrap_installation_required") is not False
            or plan.get("blockers") != []
            or type(paths) is not list or not paths
            or any(type(p) is not str or not (p in ("version", "release-manifest.json")
                or (p.startswith("dashboard/web/") and Path(p).suffix.lower() in
                    (".css", ".js", ".html", ".htm", ".svg", ".png", ".ico", ".woff", ".woff2", ".map")))
                or Path(p).as_posix() != p or ".." in Path(p).parts
                for p in paths)
            or len(set(paths)) != len(paths)
            or plan.get("file_count") != len(paths)):
        raise InstalledTransactionBlocked("restart_free_exact_file_plan_required")
    digest = review.get("verified_archive_sha256")
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise InstalledTransactionBlocked("verified_archive_digest_required")
    return digest, paths


def _validate_restart_candidate(report):
    """Validate the exact diagnostic candidate without granting admission."""
    review = report.get("operational_release_review") or {}
    plan = (report.get("release_impact") or {}).get("control_plane_restart_plan") or {}
    digest = review.get("verified_archive_sha256")
    paths = plan.get("changed_paths")
    if (review.get("artifact_origin_verified") is not True
            or review.get("target_tree_bound_to_signed_tar") is not True
            or type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or plan.get("status") != "restart_candidate_review_only"
            or plan.get("live_no_drain_authorized") is not False
            or plan.get("blocking_path_count") != 0
            or plan.get("blocking_paths") != []
            or type(paths) is not list or not paths):
        raise InstalledTransactionBlocked("exact_signed_restart_candidate_required")
    python_count = 0
    for p in paths:
        if (type(p) is not str or Path(p).is_absolute()
                or Path(p).as_posix() != p or ".." in Path(p).parts
                or "game_uptime" in p or "maintenance_hold" in p
                or "__pycache__" in Path(p).parts):
            raise InstalledTransactionBlocked("unsafe_restart_candidate_path")
        if p.startswith("dashboard/") and p.endswith(".py"):
            python_count += 1
        elif not (p in ("version", "release-manifest.json")
                  or (p.startswith("dashboard/web/") and Path(p).suffix.lower() in
                      (".css", ".js", ".html", ".htm", ".svg", ".png", ".ico", ".woff", ".woff2", ".map"))):
            raise InstalledTransactionBlocked("unsupported_restart_candidate_path")
    fixed = (report.get("release_impact") or {}).get("fixed_file_transaction_plan") or {}
    fixed_paths = fixed.get("changed_paths")
    if (len(set(paths)) != len(paths) or not python_count
            or python_count != plan.get("candidate_python_file_count")
            or fixed.get("status") != "compatible_file_plan_only"
            or fixed.get("bootstrap_installation_required") is not False
            or fixed.get("blockers") != []
            or type(fixed_paths) is not list
            or any(type(p) is not str for p in fixed_paths)
            or len(fixed_paths) != len(paths)
            or set(fixed_paths) != set(paths)
            or fixed.get("file_count") != len(paths)):
        raise InstalledTransactionBlocked("restart_candidate_inventory_mismatch")
    return digest, paths


def _select_candidate(report):
    impact = report.get("release_impact") or {}
    if (impact.get("control_plane_restart_plan") or {}).get("status") == "restart_candidate_review_only":
        digest, paths = _validate_restart_candidate(report)
        return digest, paths, True
    digest, paths = _validate_static_plan(report)
    return digest, paths, False


def _validate_plan(report):
    digest, paths, restart_required = _select_candidate(report)
    review = report.get("operational_release_review") or {}
    blockers = list((report.get("operational_execution_boundary") or {}).get("blockers", []))
    if not all(review.get(key) is True for key in (
            "operational_guarantees_complete", "operational_quiescence_acked",
            "external_jobs_acked", "durable_cross_host_recovery_verified")):
        blockers.append("positive_operational_admission_missing")
    if restart_required:
        plan = report["release_impact"]["control_plane_restart_plan"]
        if plan.get("service_ownership_verified") is not True:
            blockers.append("restart_service_ownership_unverified")
        if plan.get("restart_rollback_verified") is not True:
            blockers.append("restart_rollback_unverified")
    if blockers:
        raise InstalledTransactionBlocked(";".join(sorted(set(blockers))))
    return digest, paths, restart_required


def _restart_count(scope):
    count = scope["restart_receipt_count"]()
    if type(count) is not int or count not in (0, 1, 2):
        raise InstalledTransactionBlocked("invalid_retained_restart_count")
    return count


def _restart_verified(scope):
    before = _restart_count(scope)
    restart = scope.get("restart_control_plane")
    if before >= 2 or not callable(restart):
        raise InstalledTransactionBlocked("retained_restart_owner_missing_or_exhausted")
    result = restart()
    if (type(result) is not dict
            or result.get("status") != "restart_transition_recorded"
            or result.get("live_no_drain_authorized") is not False
            or result.get("sequence") != before + 1
            or _restart_count(scope) != before + 1):
        raise InstalledTransactionBlocked("restart_transition_not_verified")


def _verify_terminal_restart(scope, restart_required, outcome):
    count = _restart_count(scope)
    allowed = (0,) if not restart_required else (
        (1,) if outcome == "verified" else (1, 2))
    if count not in allowed:
        raise InstalledTransactionBlocked("terminal_restart_receipts_mismatch")


def _execute_file_transaction(engine, scope, *, restart_required=False):
    """Shared application/rollback orchestration under retained admission."""
    if (scope.get("all_mutators_fenced") is not True
            or scope.get("external_jobs_acked") is not True):
        raise InstalledTransactionBlocked("retained_operational_guarantees_missing")
    if _restart_count(scope) != 0:
        raise InstalledTransactionBlocked("fresh_transaction_has_restart_receipts")
    if restart_required and not callable(scope.get("restart_control_plane")):
        raise InstalledTransactionBlocked("retained_restart_owner_missing")
    scope["checkpoint"]()
    try:
        engine.apply()
        if restart_required:
            _restart_verified(scope)
        engine.verify_terminal("verified")
        _verify_terminal_restart(scope, restart_required, "verified")
        scope["checkpoint"]()
        return "verified"
    except Exception:
        # An uncertain restart must not be treated as a verified rollback.
        # The retained checkpoint rejects an unrecorded daemon replacement.
        scope["checkpoint"]()
        engine.rollback()
        if restart_required:
            _restart_verified(scope)
        engine.verify_terminal("rolled_back")
        _verify_terminal_restart(scope, restart_required, "rolled_back")
        scope["checkpoint"]()
        return "rolled_back"


def _write_status(workspace, report, status):
    path = workspace / "game-uptime-transaction.json"
    temporary = workspace / (".journal-" + uuid.uuid4().hex)
    raw = (json.dumps({**report, "status": status}, sort_keys=True,
                      separators=(",", ":")) + "\n").encode()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    folder = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)
    return hashlib.sha256(raw).hexdigest()


def _engine(module, workspace, identity, scope, digest, tx):
    return module.FileTransaction(workspace, INSTALLED, TARGET,
        transaction_id=tx, release_sha256=digest, checkpoint=scope["checkpoint"],
        product_identity=identity, _installed_scope=scope)


def _require_trusted_snapshot(target):
    if os.geteuid() != 0 or Path(__file__) != SNAPSHOT / "update-manager/game-uptime-installed-transaction.py":
        raise InstalledTransactionBlocked("audited_root_updater_snapshot_required")
    # The entire independent snapshot, not the candidate or installed DSM,
    # is the import root for privileged review and transaction modules.
    for folder in (Path("/"), Path("/usr"), Path("/usr/local"), Path("/usr/local/libexec"), SNAPSHOT):
        _trusted(folder, directory=True)
    for directory, dirs, files in os.walk(SNAPSHOT, followlinks=False):
        _trusted(Path(directory), directory=True)
        for name in dirs:
            _trusted(Path(directory) / name, directory=True)
        for name in files:
            _trusted(Path(directory) / name)
    if Path(target) != TARGET:
        raise InstalledTransactionBlocked("fixed_reviewed_payload_required")
    for folder in (Path("/var"), Path("/var/lib"), STATE, TARGET.parent, TARGET):
        _trusted(folder, directory=True)


def run(target):
    _require_trusted_snapshot(target)
    preflight = _load("game-uptime-preflight.py")
    review = preflight.collect_operational_review(INSTALLED, TARGET)
    # No holds, backups or mutations before positive independent admission.
    digest, paths, restart_required = _validate_plan(review)
    _require_forward_version(INSTALLED, TARGET)
    lease = _load("game-uptime-local-scope-lease.py")
    module = _load("game-uptime-file-transaction.py")
    identity_probe = _load("game-uptime-live-daemon-identity.py")
    from pwd import getpwnam
    from grp import getgrnam
    controller = identity_probe._systemd_status(identity_probe.CONTROLLER_UNIT)
    worker = identity_probe._systemd_status("dsm-dashboard-worker.service")
    user = getpwnam(controller["User"])
    uid, gid = user.pw_uid, user.pw_gid
    if uid <= 0 or gid <= 0 or getpwnam(worker["User"]).pw_uid != uid:
        raise InstalledTransactionBlocked("installed_service_account_mismatch")
    # The actual registry and SSH pins are checked again by the retained owner.
    _trusted(TRUST, directory=True)
    for name in ("agent-session-id", "agent-session-endpoints.json"):
        _trusted(TRUST / name)
    hybrid = (TRUST / "agent-session-id").read_text().strip()
    endpoints = json.loads((TRUST / "agent-session-endpoints.json").read_text())
    ids = sorted([hybrid, *endpoints.keys()])
    if len(ids) != len(set(ids)):
        raise InstalledTransactionBlocked("invalid_pinned_agent_partition")
    tx = uuid.uuid4().hex
    issued = int(time.time())
    options = dict(transaction_id=tx, release_sha256=digest,
                   issued_at=issued, expires_at=issued+900, expected_agent_ids=ids,
                   local_hybrid_agent_id=hybrid, expected_controller_uid=uid,
                   expected_worker_uid=uid, operator_reviewed=True)
    workspace = STATE / ("transaction-" + tx)
    with lease.retain_installed_distributed_scopes(**options) as scope:
        if (scope.get("all_mutators_fenced") is not True
                or scope.get("external_jobs_acked") is not True):
            raise InstalledTransactionBlocked("retained_operational_guarantees_missing")
        scope["checkpoint"]()
        proof = _load("game-uptime-operational-release-review.py").verify_reviewed_artifact(TARGET)
        if (proof.get("artifact_origin_verified") is not True
                or proof.get("target_tree_bound_to_signed_tar") is not True
                or proof.get("verified_archive_sha256") != digest):
            raise InstalledTransactionBlocked("signed_target_changed_under_retained_scope")
        _require_forward_version(INSTALLED, TARGET)
        scope["checkpoint"]()
        workspace.mkdir(mode=0o700)
        parent = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        engine = _engine(module, workspace, (uid, gid), scope, digest, tx)
        # Recheck both classifiers and signed binding immediately before snapshot.
        impact = preflight.plan.analyze(INSTALLED, TARGET)
        if _select_candidate({"release_impact": impact,
                              "operational_release_review": proof}) != (digest, paths, restart_required):
            raise InstalledTransactionBlocked("exact_file_plan_changed")
        if restart_required:
            engine.prepare_control_plane(impact["control_plane_restart_plan"])
        else:
            engine.prepare(paths)
        if engine.requires_control_plane_restart() is not restart_required:
            raise InstalledTransactionBlocked("product_journal_restart_mode_mismatch")
        report = {"kind": "DSM928InstalledUptimeTransaction", "schema_version": 1,
                  "scope": {key: options[key] for key in ("transaction_id", "release_sha256",
                      "issued_at", "expires_at", "expected_agent_ids")},
                  "local_hybrid_agent_id": hybrid,
                  "product_file_journal_sha256": engine.journal_digest(),
                  "product_identity": [uid, gid], "live_no_drain_authorized": False}
        _write_status(workspace, report, "prepared")
        try:
            outcome = _execute_file_transaction(engine, scope, restart_required=restart_required)
        except Exception:
            _write_status(workspace, report, "manual_recovery_required")
            raise
        terminal = _write_status(workspace, report, outcome)
    # Persistent holds bridge the transition to the explicitly reviewed
    # recovery session. A disconnect or expired window never clears them.
    with lease.retain_installed_distributed_scopes(**options, recover_existing=True) as scope:
        engine = _engine(module, workspace, (uid, gid), scope, digest, tx)
        if engine.journal_digest() != report["product_file_journal_sha256"]:
            raise InstalledTransactionBlocked("product_file_journal_changed")
        if engine.requires_control_plane_restart() is not restart_required:
            raise InstalledTransactionBlocked("product_journal_restart_mode_mismatch")
        engine.verify_terminal(outcome)
        _verify_terminal_restart(scope, restart_required, outcome)
        result = scope["finalize_terminal"](terminal)
        if result.get("status") != "installed_terminal_holds_released":
            raise InstalledTransactionBlocked("terminal_release_incomplete")
    return {"status": outcome, "transaction_id": tx, "game_drain_performed": False,
            "terminal_holds_released": True}


def _validate_recovery_report(report, tx, now):
    """Recovery never adopts a new release, inventory or lease window."""
    if (type(tx) is not str or not re.fullmatch(r"[0-9a-f]{32}", tx)
            or type(report) is not dict or set(report) != {
                "kind", "schema_version", "scope", "local_hybrid_agent_id",
                "product_file_journal_sha256", "product_identity",
                "live_no_drain_authorized", "status"}
            or report["kind"] != "DSM928InstalledUptimeTransaction"
            or report["schema_version"] != 1
            or report["live_no_drain_authorized"] is not False
            or report["status"] not in ("prepared", "verified", "rolled_back", "recovered_rollback")):
        raise InstalledTransactionBlocked("installed_recovery_journal_invalid_or_manual_review_required")
    scope = report["scope"]
    identity = report["product_identity"]
    if (type(scope) is not dict or set(scope) != {
            "transaction_id", "release_sha256", "issued_at", "expires_at",
            "expected_agent_ids"}
            or scope["transaction_id"] != tx
            or any(type(x) is not str or not re.fullmatch(r"[0-9a-f]{64}", x)
                   for x in (scope["release_sha256"], report["product_file_journal_sha256"]))
            or type(scope["issued_at"]) is not int or type(scope["expires_at"]) is not int
            or not 0 < scope["issued_at"] <= now < scope["expires_at"] <= scope["issued_at"] + 900
            or type(identity) is not list or len(identity) != 2
            or any(type(x) is not int or x <= 0 for x in identity)):
        raise InstalledTransactionBlocked("installed_recovery_binding_or_lease_invalid")
    ids = scope["expected_agent_ids"]
    if (type(ids) is not list or not 2 <= len(ids) <= 64
            or any(type(x) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", x) for x in ids)
            or ids != sorted(set(ids))
            or report["local_hybrid_agent_id"] not in ids):
        raise InstalledTransactionBlocked("installed_recovery_inventory_invalid")
    return {**scope, "local_hybrid_agent_id": report["local_hybrid_agent_id"],
            "expected_controller_uid": identity[0], "expected_worker_uid": identity[0],
            "recover_existing": True, "operator_reviewed": True}


def _read_recovery_report(workspace):
    _trusted(workspace, directory=True)
    if stat.S_IMODE(workspace.lstat().st_mode) != 0o700:
        raise InstalledTransactionBlocked("installed_recovery_workspace_not_private")
    path = workspace / "game-uptime-transaction.json"
    _trusted(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        def fingerprint(item):
            return (item.st_dev, item.st_ino, item.st_uid, item.st_mode, item.st_nlink,
                    item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 < before.st_size <= 65536
                or fingerprint(before) != fingerprint(path.lstat())):
            raise InstalledTransactionBlocked("installed_recovery_journal_untrusted")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(65537)
        if (len(raw) != before.st_size or fingerprint(before) != fingerprint(os.fstat(fd))
                or fingerprint(before) != fingerprint(path.lstat())):
            raise InstalledTransactionBlocked("installed_recovery_journal_changed")
    finally:
        os.close(fd)
    report = json.loads(raw)
    if raw != (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode():
        raise InstalledTransactionBlocked("installed_recovery_journal_not_canonical")
    return report, hashlib.sha256(raw).hexdigest()


def recover(tx):
    """Reacquire only the original, still valid installed recovery scope.

    No fresh hold, lease extension, ordinary updater, or decision reversal.
    Missing/expired/partially released evidence stays for manual review.
    """
    _require_trusted_snapshot(TARGET)
    if type(tx) is not str or not re.fullmatch(r"[0-9a-f]{32}", tx):
        raise InstalledTransactionBlocked("invalid_installed_recovery_transaction")
    workspace = STATE / ("transaction-" + tx)
    report, terminal = _read_recovery_report(workspace)
    options = _validate_recovery_report(report, tx, int(time.time()))
    digest = options["release_sha256"]
    review = _load("game-uptime-operational-release-review.py").evaluate(TARGET)
    if (review.get("artifact_origin_verified") is not True
            or review.get("target_tree_bound_to_signed_tar") is not True
            or review.get("verified_archive_sha256") != digest):
        raise InstalledTransactionBlocked("original_signed_recovery_payload_unverified")
    lease = _load("game-uptime-local-scope-lease.py")
    module = _load("game-uptime-file-transaction.py")
    with lease.retain_installed_distributed_scopes(**options) as scope:
        if (scope.get("all_mutators_fenced") is not True
                or scope.get("external_jobs_acked") is not True):
            raise InstalledTransactionBlocked("retained_operational_guarantees_missing")
        if _read_recovery_report(workspace) != (report, terminal):
            raise InstalledTransactionBlocked("installed_recovery_journal_changed")
        engine = _engine(module, workspace, tuple(report["product_identity"]), scope, digest, tx)
        if engine.journal_digest() != report["product_file_journal_sha256"]:
            raise InstalledTransactionBlocked("product_file_journal_changed")
        outcome = report["status"]
        restart_required = engine.requires_control_plane_restart()
        if outcome == "prepared":
            for prefix in ("terminal-", "terminal-confirmation-", "released-"):
                if os.path.lexists(STATE / (prefix + tx + ".json")):
                    raise InstalledTransactionBlocked("existing_terminal_decision_requires_review")
            # The before/after file journal handles an interrupted mixed
            # state. A failed rollback keeps the prepared journal and holds.
            count = _restart_count(scope)
            if not restart_required and count:
                raise InstalledTransactionBlocked("unexpected_static_restart_receipts")
            if restart_required and count == 2:
                # Both restart transitions are already durable. Never apply a
                # third restart or change files behind the recorded daemons.
                engine.verify_terminal("recovered_rollback")
            else:
                engine.rollback()
                if restart_required:
                    _restart_verified(scope)
            outcome = "recovered_rollback"
            engine.verify_terminal(outcome)
            _verify_terminal_restart(scope, restart_required, outcome)
            scope["checkpoint"]()
            terminal = _write_status(workspace, report, outcome)
        else:
            # An already durable decision is immutable; only finish it.
            engine.verify_terminal(outcome)
            _verify_terminal_restart(scope, restart_required, outcome)
        scope["checkpoint"]()
        result = scope["finalize_terminal"](terminal)
        if result.get("status") != "installed_terminal_holds_released":
            raise InstalledTransactionBlocked("terminal_release_incomplete")
    return {"status": outcome, "transaction_id": tx, "game_drain_performed": False,
            "terminal_holds_released": True}


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--recover":
            result = recover(sys.argv[2])
        elif len(sys.argv) == 2:
            result = run(sys.argv[1])
        else:
            raise InstalledTransactionBlocked("exactly_one_reviewed_payload_or_recovery_id_required")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "verified" else 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)[:1000],
                          "ordinary_draining_fallback": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
