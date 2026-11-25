#!/usr/bin/env python3
"""Installed #928 execution owner. No game/service/database operations.

Initial admission remains fail-closed: the existing operational review and
retained scope do not yet positively attest all mutators and external jobs.
The fixed file transaction is intentionally limited to restart-free static
web assets and release metadata. Python/control-plane restarts are not
silently treated as compatible. No caller-provided approval booleans.
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


def _validate_plan(report):
    review = report.get("operational_release_review") or {}
    plan = (report.get("release_impact") or {}).get("fixed_file_transaction_plan") or {}
    blockers = list((report.get("operational_execution_boundary") or {}).get("blockers", []))
    if not all(review.get(key) is True for key in (
            "artifact_origin_verified", "target_tree_bound_to_signed_tar",
            "operational_guarantees_complete", "operational_quiescence_acked",
            "external_jobs_acked", "durable_cross_host_recovery_verified")):
        blockers.append("positive_operational_admission_missing")
    paths = plan.get("changed_paths")
    if (plan.get("status") != "compatible_file_plan_only"
            or type(paths) is not list or not paths or
            any(type(p) is not str or not (p in ("version", "release-manifest.json")
                or (p.startswith("dashboard/web/") and Path(p).suffix.lower() in
                    (".css", ".js", ".html", ".htm", ".svg", ".png", ".ico", ".woff", ".woff2", ".map")))
                for p in paths)):
        blockers.append("restart_free_exact_file_plan_required")
    if blockers:
        raise InstalledTransactionBlocked(";".join(sorted(set(blockers))))
    digest = review.get("verified_archive_sha256")
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise InstalledTransactionBlocked("verified_archive_digest_required")
    return digest, paths


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


def run(target):
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
    preflight = _load("game-uptime-preflight.py")
    review = preflight.collect_operational_review(INSTALLED, TARGET)
    # No holds, backups or mutations before positive independent admission.
    digest, paths = _validate_plan(review)
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
        workspace.mkdir(mode=0o700)
        parent = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        engine = _engine(module, workspace, (uid, gid), scope, digest, tx)
        # Recheck exact reviewed plan immediately before snapshot.
        if preflight.plan.analyze(INSTALLED, TARGET)["fixed_file_transaction_plan"]["changed_paths"] != paths:
            raise InstalledTransactionBlocked("exact_file_plan_changed")
        engine.prepare(paths)
        report = {"kind": "DSM928InstalledUptimeTransaction", "schema_version": 1,
                  "scope": {key: options[key] for key in ("transaction_id", "release_sha256",
                      "issued_at", "expires_at", "expected_agent_ids")},
                  "local_hybrid_agent_id": hybrid,
                  "product_file_journal_sha256": engine.journal_digest(),
                  "product_identity": [uid, gid], "live_no_drain_authorized": False}
        _write_status(workspace, report, "prepared")
        try:
            engine.apply()
            engine.verify_terminal("verified")
            scope["checkpoint"]()
            outcome = "verified"
        except Exception:
            try:
                engine.rollback()
                engine.verify_terminal("rolled_back")
                scope["checkpoint"]()
                outcome = "rolled_back"
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
        engine.verify_terminal(outcome)
        result = scope["finalize_terminal"](terminal)
        if result.get("status") != "installed_terminal_holds_released":
            raise InstalledTransactionBlocked("terminal_release_incomplete")
    return {"status": outcome, "transaction_id": tx, "game_drain_performed": False,
            "terminal_holds_released": True}


def main():
    try:
        if len(sys.argv) != 2:
            raise InstalledTransactionBlocked("exactly_one_reviewed_payload_required")
        result = run(sys.argv[1])
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "verified" else 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)[:1000],
                          "ordinary_draining_fallback": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
