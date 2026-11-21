"""Full update.sh main() order in an owner-marked disposable filesystem only."""
from __future__ import annotations

import subprocess
import json
from importlib.machinery import SourceFileLoader
import importlib.util
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests/fixtures/update_928_main_path_rehearsal.sh"
UPDATER = ROOT / "update.sh"

from update_game_uptime_real_update_functions_test import create_tiny_release_fixture


def fixture_signer():
    path = ROOT / "update-manager/game-uptime-fixture-attestation.py"
    loader = SourceFileLoader("dsm928_test_package_signer", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    helper = importlib.util.module_from_spec(spec)
    loader.exec_module(helper)
    return helper


def main_rehearsal(workspace: Path, mode="success") -> subprocess.CompletedProcess:
    return subprocess.run(
        ("bash", str(HARNESS), str(workspace), str(UPDATER), mode),
        capture_output=True, text=True, check=False, timeout=35,
    )


class MainPathRehearsalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsm928-main-path-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        create_tiny_release_fixture(self.root)
        # The real updater's semantic-version gate needs valid version strings.
        (self.root/"installed/version").write_text("2.0.998")
        (self.root/"new-payload/version").write_text("2.0.999")
        self.installed = self.root/"installed"
        self.world = self.installed/"runtime/hybrid-instance-storage/minecraft005/world/level.dat"
        self.upload = self.installed/"runtime/artifact-transfers/job-001/upload.part"

    def prepare_no_drain_fixture(self):
        # Keep the checked-out source's actual backup/apply/rollback file
        # routines, but ensure every release change is compatible with the
        # STRICT control-plane-only classifier. Runtime/database state is
        # identical, whereas the dashboard and version are changed.
        for tree in (self.root / "installed", self.root / "new-payload"):
            supervisor = tree / "agents/linux/runtime/console_supervisor.py"
            supervisor.parent.mkdir(parents=True, exist_ok=True)
            supervisor.write_text("stable supervisor fixture\\n")
        target_db = self.root / "new-payload/data/database.txt"
        target_db.parent.mkdir(parents=True, exist_ok=True)
        target_db.write_bytes((self.installed / "data/database.txt").read_bytes())
        (self.installed / "version").write_text("2.0.998-fixture")
        (self.root / "new-payload/version").write_text("2.0.999-fixture")
        fixture_signer().seal_test_fixture(self.root)

    def test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains(self):
        self.prepare_no_drain_fixture()
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 0,
                         outcome.stderr[-3000:] + outcome.stdout[-1900:])
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.999-fixture")
        receipt = json.loads(
            (self.root / "dsm928-composite-journal/game-uptime-transaction.json").read_text())
        self.assertTrue(receipt["strict_inventory"])
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(len(receipt["original_units"]), 2)
        self.assertFalse(receipt["live_no_drain_authorized"])
        self.assertIn("DSM928MainDisposableNoDrainRehearsal", outcome.stdout)
        self.assertTrue(json.loads(outcome.stdout.strip().splitlines()[-1])["fixture_package_attested"])
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertEqual(len(list((self.root / "backups").glob("*.tar.gz"))), 1)
        self.assertFalse((self.root / "steps").exists(), "never call stop/start service hooks")

    def test_disposable_no_drain_main_injected_failure_rolls_back_without_draining(self):
        self.prepare_no_drain_fixture()
        outcome = main_rehearsal(self.root, "no_drain_fail_after_apply")
        self.assertEqual(outcome.returncode, 2, outcome.stderr[-2500:])
        self.assertIn("EXPECTED_DISPOSABLE_ROLLBACK_CONFIRMED", outcome.stdout)
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        receipt = json.loads(
            (self.root / "dsm928-composite-journal/game-uptime-transaction.json").read_text())
        self.assertEqual(receipt["status"], "rolled_back")
        self.assertTrue(receipt["strict_inventory"])
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertFalse((self.root / "steps").exists())

    def test_disposable_no_drain_main_rejects_new_game_before_any_backup(self):
        self.prepare_no_drain_fixture()
        (self.root / "fixture-add-game-during-handoff").write_text("new game")
        outcome = main_rehearsal(self.root, "no_drain_drift")
        self.assertEqual(outcome.returncode, 2, outcome.stdout[-800:] + outcome.stderr[-1300:])
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])
        self.assertFalse((self.root / "steps").exists())

    def test_disposable_no_drain_main_rejects_unclassified_schema_change(self):
        self.prepare_no_drain_fixture()
        unexpected = self.root / "new-payload/database/migrations/099.sql"
        unexpected.parent.mkdir(parents=True, exist_ok=True)
        unexpected.write_text("ALTER TABLE x")
        # A newly signed package is still blocked by the independent impact
        # classifier; HMAC verification must not override release safety.
        fixture_signer().seal_test_fixture(self.root)
        outcome = main_rehearsal(self.root, "no_drain_unknown_file")
        self.assertEqual(outcome.returncode, 2, outcome.stderr[-1300:])
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_unsigned_payload_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        (self.root / ".dsm928-fixture-package-seal.json").unlink()
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual((self.installed / "version").read_text(), "2.0.998-fixture")
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])
        self.assertFalse((self.root / "dsm928-composite-journal").exists())

    def test_disposable_no_drain_modified_signed_payload_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        (self.root / "new-payload/dashboard/web/presentation.js").write_text("injected")
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual((self.installed / "version").read_text(), "2.0.998-fixture")
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_forged_mac_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        path = self.root / ".dsm928-fixture-package-seal.json"
        forged = json.loads(path.read_text())
        forged["hmac_sha256"] = "f" * 64
        path.write_text(json.dumps(forged))
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_key_symlink_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        key = self.root / ".dsm928-fixture-signer.key"
        other = self.root / "different.key"
        other.write_bytes(key.read_bytes())
        key.unlink()
        key.symlink_to(other)
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_main_refuses_without_explicit_fixture_opt_in(self):
        self.prepare_no_drain_fixture()
        outcome = main_rehearsal(self.root, "no_drain_no_env")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_actual_main_path_success_preserves_world_and_checks_guard_order(self):
        outcome = main_rehearsal(self.root)
        self.assertEqual(outcome.returncode, 0, outcome.stderr[-2500:] + outcome.stdout[-1500:])
        self.assertEqual((self.installed/"version").read_text().strip(), "2.0.999")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertEqual((self.installed/"data/database.txt").read_text(), "db durable")
        self.assertEqual((self.installed/"runtime/hybrid-agent-state/backup-index/keep.txt").read_text(),"protected")
        self.assertEqual((self.installed/"config/dsm.conf").read_text().splitlines()[0], 'DSM_VERSION="2.0.999"')
        self.assertEqual(len(list((self.root/"backups").glob("dsm-before-update-*.tar.gz"))), 1)
        steps=(self.root/"steps").read_text().splitlines()
        self.assertEqual(steps, [
            "guard:allow-managed", "capture-games", "capture-services",
            "stop-controller", "stop-games", "guard:strict",
            "backup-database-stub", "guard:strict", "migrate-database-stub",
            "start-controller", "start-games",
        ])
        self.assertFalse((self.root/"staging").exists())
        self.assertFalse((self.root/"installed.update-preserved").exists())

    def test_actual_main_path_after_swap_failure_restores_old_product_and_world(self):
        outcome = main_rehearsal(self.root, "fail_after_apply")
        self.assertNotEqual(outcome.returncode, 0, outcome.stdout[-2500:] + outcome.stderr[-1800:])
        self.assertEqual((self.installed/"version").read_text().strip(), "2.0.998")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertEqual((self.installed/"data/database.txt").read_text(), "db durable")
        self.assertEqual((self.installed/"runtime/hybrid-agent-state/backup-index/keep.txt").read_text(),"protected")
        steps=(self.root/"steps").read_text().splitlines()
        self.assertIn("migrate-database-stub",steps)
        self.assertIn("restore-database-stub",steps)
        self.assertIn("start-controller",steps)
        self.assertIn("start-games",steps)
        self.assertNotIn("UNEXPECTED-SYSTEMCTL", steps)
        self.assertIn("stub-daemon-reload",steps)
        self.assertFalse((self.root/"installed.update-preserved").exists())

    def test_no_disposable_marker_blocks_before_real_main(self):
        (self.root/"fixture-owner").unlink()
        outcome = main_rehearsal(self.root)
        self.assertNotEqual(outcome.returncode, 0)
        self.assertEqual((self.installed/"version").read_text(), "2.0.998")
        self.assertFalse((self.root/"steps").exists())

    def test_symlinked_workspace_is_blocked_before_real_main(self):
        link = self.root.with_name(self.root.name+"-alias")
        link.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(link.unlink)
        outcome = main_rehearsal(link)
        self.assertNotEqual(outcome.returncode, 0)
        self.assertEqual((self.installed/"version").read_text(), "2.0.998")
        self.assertFalse((self.root/"steps").exists())

    def test_invalid_mode_blocks_before_real_main(self):
        outcome = main_rehearsal(self.root, "production")
        self.assertNotEqual(outcome.returncode, 0)
        self.assertEqual((self.installed/"version").read_text(), "2.0.998")
        self.assertFalse((self.root/"steps").exists())


if __name__ == "__main__":
    unittest.main()
