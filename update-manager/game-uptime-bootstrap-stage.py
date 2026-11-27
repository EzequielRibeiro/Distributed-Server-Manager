#!/usr/bin/env python3
"""Stage the #928 installation inputs from one independently signed release.

No service operation, publication, local configuration enrollment or live
update authorization occurs here. Run the audited script with -I -S -B.
The resulting bundle is for an explicitly approved conventional maintenance
window; existing snapshots, pins, recovery state and backups are untouched.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

STATE = Path("/var/lib/capivara-dsm-928")
REVIEWED = STATE / "reviewed-release"
MODULES = (
    "game_uptime_ssh_transport.py", "game_uptime_hold_coordinator.py",
    "game_uptime_maintenance_hold.py", "game_uptime_transaction_binding.py",
    "game_uptime_privileged_flock.py", "game_uptime_finalization_flock.py",
    "game_uptime_privileged_journal_witness.py",
    "game_uptime_wire_replay_service.py", "game_uptime_durable_wire_replay.py",
)


def _load(filename):
    spec = importlib.util.spec_from_file_location(
        filename.replace("-", "_"), Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trusted(path, *, directory=False):
    info = path.lstat()
    if (info.st_uid != os.geteuid() or info.st_mode & 0o7022
            or (not stat.S_ISDIR(info.st_mode) if directory else
                not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
        raise ValueError("untrusted bootstrap input: " + str(path))


def _trusted_tree(root, *, no_bytecode=False):
    _trusted(root, directory=True)
    def fail(exc):
        raise exc
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        for name in dirs:
            _trusted(Path(folder) / name, directory=True)
            if no_bytecode and name == "__pycache__":
                raise ValueError("bytecode directory in privileged snapshot")
        for name in files:
            path = Path(folder) / name
            _trusted(path)
            if no_bytecode and path.suffix in (".pyc", ".pyo"):
                raise ValueError("bytecode file in privileged snapshot")


def _copy_file(source, destination, *, mode=None):
    _trusted(source)
    if os.path.lexists(destination):
        raise ValueError("bootstrap destination already exists")
    shutil.copy2(source, destination, follow_symlinks=False)
    if mode is not None:
        destination.chmod(mode)
    _trusted(destination)
    if source.read_bytes() != destination.read_bytes():
        raise ValueError("bootstrap copy verification failed")


def _stage_bundle(reviewed, stage, *, version, commit, digest):
    """Internal staging operation; caller owns signed-artifact verification."""
    if (not re.fullmatch(r"[A-Za-z0-9.+-]+", version)
            or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("invalid reviewed release identity")
    _trusted(stage, directory=True)
    if any(stage.iterdir()):
        raise ValueError("bootstrap stage must be empty")
    payload = reviewed / "payload"
    _trusted_tree(payload)
    if (payload / "version").read_text().strip() != version:
        raise ValueError("bootstrap payload version mismatch")
    if (reviewed / "reviewed-commit").read_text() != commit + "\n":
        raise ValueError("bootstrap commit mismatch")
    updater = stage / "updater"
    agent = stage / "agent"
    baseline = stage / "installed-baseline"
    versions = stage / "supervisor-versions"
    for path in (updater, agent, baseline, versions):
        path.mkdir(mode=0o700)
    for name in ("update-manager", "agents", "dashboard", "systemd"):
        source = payload / name
        _trusted_tree(source, no_bytecode=True)
        shutil.copytree(source, updater / name)
    runtime = payload / "agents/linux/runtime"
    for name in MODULES:
        _copy_file(runtime / name, agent / name, mode=0o644)
    for folder in (updater, agent):
        _trusted_tree(folder, no_bytecode=True)
    # Retain the original signed package, not a hash of a mutable installation.
    prefix = "capivara-dsm-" + version
    for name in ("reviewed-commit", prefix + ".tar.gz", prefix + ".manifest.json",
                 prefix + ".provenance.json", prefix + ".provenance.sig"):
        source = reviewed / name
        _trusted(source)
        shutil.copy2(source, baseline / name, follow_symlinks=False)
        _trusted(baseline / name)
    shutil.copytree(payload, baseline / "payload")
    source = runtime / "console_supervisor.py"
    supervisor = _load("game-uptime-supervisor-stage.py")
    pin = hashlib.sha256(source.read_bytes()).hexdigest()
    supervisor.stage_supervisor(source, versions, expected_sha256=pin)
    (versions / "active-pin.json").write_text(json.dumps({"sha256": pin}) + "\n")
    (versions / "active-pin.json").chmod(0o644)
    versions.chmod(0o755)
    return {"kind": "DSM928BootstrapStagedBundle", "schema_version": 1,
            "version": version, "git_commit": commit, "archive_sha256": digest,
            "supervisor_sha256": pin, "agent_module_count": len(MODULES),
            "published": False, "live_no_drain_authorized": False}


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise SystemExit("run as root with no arguments, from audited signed source")
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise SystemExit("use python3 -I -S -B")
    for path in (Path("/"), Path("/var"), Path("/var/lib"), STATE, REVIEWED):
        _trusted(path, directory=True)
    if any(os.path.lexists(path) for path in (
            STATE / "no-drain-pending.json",
            Path("/run/capivara-dsm/no-drain-maintenance.json"))):
        raise SystemExit("existing transaction requires review")
    review = _load("game-uptime-operational-release-review.py")
    proof = review.verify_reviewed_artifact(REVIEWED / "payload")
    if (proof.get("artifact_origin_verified") is not True
            or proof.get("target_tree_bound_to_signed_tar") is not True):
        raise SystemExit("signed bootstrap source not verified")
    version = (REVIEWED / "payload/version").read_text().strip()
    stage = Path(tempfile.mkdtemp(prefix="bootstrap-stage-", dir=STATE))
    try:
        result = _stage_bundle(REVIEWED, stage, version=version,
                               commit=proof["verified_release_commit"],
                               digest=proof["verified_archive_sha256"])
        if review.verify_reviewed_artifact(REVIEWED / "payload") != proof:
            raise ValueError("reviewed bootstrap source changed")
        baseline = review._verify_fixed_artifact(
            stage / "installed-baseline/payload", stage / "installed-baseline")
        if baseline != proof:
            raise ValueError("staged baseline differs from signed source")
        (stage / "bundle.json").write_text(json.dumps(result, sort_keys=True) + "\n")
    except BaseException:
        shutil.rmtree(stage)
        raise
    print(json.dumps({**result, "stage": str(stage)}, sort_keys=True))


if __name__ == "__main__":
    main()
