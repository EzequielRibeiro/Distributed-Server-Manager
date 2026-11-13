"""Real update.sh file apply/rollback functions on tiny disposable trees only.

No update.sh main(), systemctl/game commands, or installed DSM root is touched.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/update_928_real_functions_rehearsal.sh"
UPDATE = ROOT / "update.sh"


def create_tiny_release_fixture(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "fixture-owner").write_text("DSM928_DISPOSABLE_FIXTURE_V1\n")
    installed = workspace / "installed"
    new = workspace / "new-payload"
    for root, ver in ((installed, "2.0.998-fixture"), (new, "2.0.999-fixture")):
        (root / "core").mkdir(parents=True)
        (root / "bin").mkdir()
        (root / "dashboard/web").mkdir(parents=True)
        (root / "version").write_text(ver)
        (root / "core/bootstrap.sh").write_text("#!/bin/sh\n")
        (root / "bin/cap").write_text("#!/bin/sh\n")
        (root / "dashboard/web/presentation.js").write_text("from-"+ver)
    (installed / "config").mkdir()
    (installed / "config/dsm.conf").write_text("DSM_VERSION=2.0.998-fixture\n")
    (installed / "runtime/hybrid-instance-storage/minecraft005/world").mkdir(parents=True)
    (installed / "runtime/hybrid-instance-storage/minecraft005/world/level.dat").write_bytes(b"saved-world-private-test")
    (installed / "runtime/hybrid-agent-state/backup-index").mkdir(parents=True)
    (installed / "runtime/hybrid-agent-state/backup-index/keep.txt").write_text("protected")
    (installed / "instances").mkdir()
    (installed / "instances/clients.json").write_text("durable")
    (installed / "game-data").mkdir()
    (installed / "game-data/cache-marker").write_text("user-owned")
    (installed / "data").mkdir()
    (installed / "data/database.txt").write_text("db durable")


def run_real_update_fns(workspace: Path, mode: str) -> subprocess.CompletedProcess:
    if mode not in {"prepare", "apply", "rollback"}:
        raise ValueError("invalid disposable updater fixture mode")
    return subprocess.run(
        ("bash", str(FIXTURE), str(workspace), str(UPDATE), mode),
        text=True, capture_output=True, check=False, timeout=30,
    )


class RealUpdateFunctionsFixtureTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dsm928-real-updater-")
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        create_tiny_release_fixture(self.workspace)
        self.original = self.workspace / "installed"
        self.world = self.original / "runtime/hybrid-instance-storage/minecraft005/world/level.dat"

    def command(self, mode):
        run = run_real_update_fns(self.workspace, mode)
        self.assertEqual(run.returncode, 0, (mode, run.stdout[-650:], run.stderr[-950:]))
        return run

    def test_actual_update_functions_retain_world_and_restore_old_product(self):
        self.command("prepare")
        files = list((self.workspace/"backups").glob("*.tar.gz"))
        self.assertEqual(len(files), 1)
        self.command("apply")
        self.assertEqual((self.original / "version").read_text(), "2.0.999-fixture")
        self.assertEqual((self.original / "dashboard/web/presentation.js").read_text(),
                         "from-2.0.999-fixture")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual((self.original/"data/database.txt").read_text(), "db durable")
        self.assertEqual((self.original/"runtime/hybrid-agent-state/backup-index/keep.txt").read_text(), "protected")
        self.command("rollback")
        self.assertEqual((self.original/"version").read_text(), "2.0.998-fixture")
        self.assertEqual((self.original/"dashboard/web/presentation.js").read_text(),
                         "from-2.0.998-fixture")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual((self.original/"data/database.txt").read_text(), "db durable")
        self.assertEqual((self.original/"runtime/hybrid-agent-state/backup-index/keep.txt").read_text(), "protected")
        self.assertFalse((self.workspace/"installed.update-preserved").exists())

    def test_fail_closed_without_marker(self):
        (self.workspace/"fixture-owner").unlink()
        run = run_real_update_fns(self.workspace, "prepare")
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse((self.workspace/"backups").exists())
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")

    def test_fail_closed_if_workspace_symlink(self):
        other = self.workspace.with_name(self.workspace.name + "-alias")
        other.symlink_to(self.workspace, target_is_directory=True)
        self.addCleanup(other.unlink)
        run = run_real_update_fns(other, "prepare")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")

    def test_rollback_requires_exactly_one_snapshot(self):
        self.command("prepare")
        files = list((self.workspace/"backups").glob("*.tar.gz"))
        (self.workspace/"backups"/"dsm-before-update-extra.tar.gz").write_bytes(files[0].read_bytes())
        run = run_real_update_fns(self.workspace, "rollback")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual((self.original/"version").read_text(), "2.0.998-fixture")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")


if __name__ == "__main__":
    unittest.main()
