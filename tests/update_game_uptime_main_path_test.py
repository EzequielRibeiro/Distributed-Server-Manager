"""Full update.sh main() order in an owner-marked disposable filesystem only."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests/fixtures/update_928_main_path_rehearsal.sh"
UPDATER = ROOT / "update.sh"

from update_game_uptime_real_update_functions_test import create_tiny_release_fixture


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

    def test_actual_main_path_success_preserves_world_and_checks_guard_order(self):
        outcome = main_rehearsal(self.root)
        self.assertEqual(outcome.returncode, 0, outcome.stderr[-2500:] + outcome.stdout[-1500:])
        self.assertEqual((self.installed/"version").read_text().strip(), "2.0.999")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
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
