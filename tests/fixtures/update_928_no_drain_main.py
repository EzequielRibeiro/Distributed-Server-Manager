#!/usr/bin/env python3
"""#928: TEST-ONLY update.sh main() no-drain transaction on an owned /tmp fixture.

This is never an update authority, never touches DSM production, and uses
synthetic game unit identities. Real backup/swap/rollback *file functions* are
called via the existing restricted shell rehearsal. No systemctl calls here.
"""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "tests"))
from update_game_uptime_real_update_functions_test import run_real_update_fns


def load_compose():
    path = REPOSITORY / "update-manager/game-uptime-isolated-compose.py"
    loader = SourceFileLoader("dsm928_main_disposable_composer", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def validate(root: Path, mode: str) -> Path:
    if mode not in {"success", "fail_after_apply"}:
        raise ValueError("unsupported disposable test mode")
    if (os.environ.get("CAPIVARA_DSM928_DISPOSABLE_MAIN") != "1"
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or Path("/opt/dsm").exists() or Path("/opt/dsm").is_symlink()):
        raise ValueError("not an isolated disposable runner")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid disposable root")
    resolved = root.resolve(strict=True)
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if resolved == temp or temp not in resolved.parents:
        raise ValueError("disposable fixture must be inside /tmp")
    if (resolved.stat().st_uid != os.geteuid()
            or resolved.stat().st_mode & 0o077):
        raise ValueError("disposable fixture must be private and owner-controlled")
    marker = resolved / "fixture-owner"
    if (marker.is_symlink() or not marker.is_file()
            or marker.read_bytes() != b"DSM928_DISPOSABLE_FIXTURE_V1\n"):
        raise ValueError("missing immutable disposable fixture marker")
    for relative in ("installed", "new-payload"):
        source = resolved / relative
        if not source.is_dir() or source.is_symlink() or source.resolve(strict=True) != source:
            raise ValueError("unsafe fixture release tree")
    return resolved


def check_preserved(root: Path) -> None:
    installed = root / "installed"
    checked = (
        ("runtime/hybrid-instance-storage/minecraft005/world/level.dat",
         b"saved-world-private-test"),
        ("runtime/hybrid-agent-state/backup-index/keep.txt", b"protected"),
        ("runtime/artifact-transfers/job-001/upload.part",
         b"in-flight-upload-private-test"),
        ("data/database.txt", b"db durable"),
    )
    for relative, expected in checked:
        if (installed / relative).read_bytes() != expected:
            raise RuntimeError("private fixture data corrupted: " + relative)


def run(root: Path, mode: str) -> int:
    compose = load_compose()
    # These are deliberately fake identities: only the real systemd E2E
    # workflow supplies live transient systemd evidence, not this CLI test.
    units = ["dsm928-e2e-dayz-001.service", "dsm928-e2e-minecraft-001.service"]
    state = {
        units[0]: {"unit": units[0], "pid": 23001, "started": 991,
                   "state": "active",
                   "unit_config_sha256": hashlib.sha256(b"fixture-dayz-unit").hexdigest()},
        units[1]: {"unit": units[1], "pid": 23002, "started": 992,
                   "state": "active",
                   "unit_config_sha256": hashlib.sha256(b"fixture-minecraft-unit").hexdigest()},
    }
    inventory_reads = [0]

    def list_units():
        inventory_reads[0] += 1
        if (root / "fixture-add-game-during-handoff").exists() and inventory_reads[0] > 1:
            return units + ["dsm928-e2e-extra-game.service"]
        return list(units)

    def inspect(unit):
        return dict(state[unit])

    def file_step(step):
        result = run_real_update_fns(root, step)
        if result.returncode != 0:
            raise RuntimeError(
                "real fixture update.sh file step failed (" + step + "): "
                + result.stderr[-350:]
            )

    def after_apply():
        if mode == "fail_after_apply":
            raise RuntimeError("injected failure after disposable file swap")

    def verify():
        check_preserved(root)

    contract = {"protocol": "v1", "schema": "22",
                "controller_api": "v2", "agent_api": "v2"}
    try:
        receipt = compose.execute_with_compatibility_gate(
            root, units, controller_contract=contract, agent_contract=contract,
            supervisor_pinned_preview=True,
            inspect=inspect, list_active_units=list_units,
            prepare_files=lambda: file_step("prepare"),
            apply_files=lambda: file_step("apply"),
            rollback_files=lambda: file_step("rollback"),
            apply_unit=after_apply,
            rollback_unit=lambda: None,
            verify=verify,
        )
    except Exception as exc:
        # Failure must NOT fall into update.sh's production error/rollback
        # handlers. Its already-durable fixture journal is preserved.
        print("DISPOSABLE_REHEARSAL_BLOCKED: " + type(exc).__name__
              + ": " + str(exc)[:250], file=sys.stderr)
        if mode == "fail_after_apply":
            journal = root / "dsm928-composite-journal/game-uptime-transaction.json"
            if (journal.is_file()
                    and json.loads(journal.read_text()).get("status") == "rolled_back"
                    and (root / "installed/version").read_text().strip()
                    == "2.0.998-fixture"):
                check_preserved(root)
                print("EXPECTED_DISPOSABLE_ROLLBACK_CONFIRMED")
        return 2

    journal = root / "dsm928-composite-journal/game-uptime-transaction.json"
    durable = json.loads(journal.read_text())
    if (receipt.get("status") != "verified"
            or receipt.get("live_no_drain_authorized") is not False
            or receipt.get("full_inventory_attested") is not True
            or durable.get("strict_inventory") is not True
            or len(durable.get("original_units", [])) != 2
            or (root / "installed/version").read_text().strip() != "2.0.999-fixture"):
        raise RuntimeError("unverified disposable transaction")
    check_preserved(root)
    print(json.dumps({
        "kind": "DSM928MainDisposableNoDrainRehearsal",
        "scope": "disposable_only_not_production",
        "status": "verified",
        "release_tier": receipt["reviewed_disposable_release_tier"],
        "units_witnessed": len(durable["original_units"]),
        "strict_inventory": True,
        "live_no_drain_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    try:
        raise SystemExit(run(validate(Path(sys.argv[1]), sys.argv[2]), sys.argv[2]))
    except (OSError, ValueError, RuntimeError) as error:
        print("DISPOSABLE_REHEARSAL_REFUSED: " + str(error)[:250], file=sys.stderr)
        raise SystemExit(2)
