#!/usr/bin/env python3
"""Real filesystem rollback exercises in a disposable temporary directory only.

Tests model file replacement and world preservation, NOT a production server,
Agent, Minecraft runtime, storage pool or backup verification integration.
"""
from __future__ import annotations
import hashlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from minecraft_staged_migration_rehearsal import RehearsalError, rehearse_staged_migration


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DisposableFilesystemMigrationTest(unittest.TestCase):
    def _run(self, *, fail_at=None):
        with tempfile.TemporaryDirectory(prefix="capivara-migration-disposable-") as name:
            root = Path(name)
            world = root / "world" / "level.dat"
            world.parent.mkdir()
            world.write_bytes(b"world data: keep unchanged")
            original_world = digest(world)
            active = root / "active"
            active.mkdir()
            (active / "neoforge.txt").write_text("26.1.2.94")
            (active / "mod.jar").write_bytes(b"existing-atm11-mod")
            stage_dir = root / "stage"
            old = root / "rollback-runtime"
            quarantine = root / "failed-runtime"
            backup = root / "backup.zip"
            expected = {
                "neoforge.txt": digest(active / "neoforge.txt"),
                "mod.jar": digest(active / "mod.jar"),
                "world/level.dat": original_world,
            }
            seen = []

            def stage():
                stage_dir.mkdir()
                (stage_dir / "neoforge.txt").write_text("26.1.2.109")
                (stage_dir / "mod.jar").write_bytes(b"next-atm11-mod")
                seen.append("stage")
                if fail_at == "stage":
                    raise RuntimeError("injected staging failure")

            def checkpoint():
                seen.append("checkpoint")
                with zipfile.ZipFile(backup, "w") as z:
                    z.write(world, "world/level.dat")
                    for item in active.iterdir():
                        z.write(item, item.name)
                with zipfile.ZipFile(backup) as z:
                    if z.testzip() is not None:
                        return {"verified": False}
                    verified = all(
                        hashlib.sha256(z.read(filename)).hexdigest() == sha
                        for filename, sha in expected.items()
                    )
                if fail_at == "checkpoint":
                    return {"verified": False}
                return {"verified": verified, "sha256": digest(backup)}

            def activate():
                seen.append("activate")
                active.rename(old)
                if fail_at == "after_old_moved":
                    raise RuntimeError("injected interruption after moving old runtime")
                stage_dir.rename(active)
                if fail_at == "activate":
                    raise RuntimeError("injected failure after swapping runtime")

            def doctor():
                seen.append("doctor")
                return fail_at != "readiness" and (active / "neoforge.txt").read_text() == "26.1.2.109"

            def commit():
                seen.append("commit")
                if fail_at == "commit":
                    raise RuntimeError("injected failure before commit")
                # A real Agent would retain rollback artifacts by policy.
                # In this disposable test only, remove the superseded runtime.
                shutil.rmtree(old)

            def rollback():
                seen.append("rollback")
                if active.exists() and old.exists():
                    active.rename(quarantine)
                if old.exists():
                    old.rename(active)
                if not active.exists() or digest(world) != original_world:
                    raise RuntimeError("world or original runtime is missing")
                for filename, sha in expected.items():
                    target = root / filename if filename.startswith("world/") else active / filename
                    if digest(target) != sha:
                        raise RuntimeError("rollback checksum mismatch")

            def cleanup():
                seen.append("cleanup")
                if stage_dir.exists():
                    shutil.rmtree(stage_dir)
                if quarantine.exists():
                    shutil.rmtree(quarantine)

            args = dict(
                revalidate=lambda: {"valid": True, "install_allowed": False},
                capacity=lambda: {"sufficient": True, "install_allowed": False},
                stage=stage, checkpoint=checkpoint, activate=activate,
                doctor=doctor, commit=commit, rollback=rollback, cleanup=cleanup,
                test_only=True,
            )
            if fail_at is None:
                result = rehearse_staged_migration(**args)
                self.assertEqual(result["status"], "rehearsal_completed")
                self.assertEqual((active / "neoforge.txt").read_text(), "26.1.2.109")
            else:
                with self.assertRaises(RehearsalError):
                    rehearse_staged_migration(**args)
                self.assertEqual((active / "neoforge.txt").read_text(), "26.1.2.94")
                self.assertEqual(digest(active / "mod.jar"), expected["mod.jar"])
            self.assertEqual(digest(world), original_world)
            self.assertNotIn("world", {p.name for p in active.iterdir()})
            return seen

    def test_full_disposable_filesystem_switch_preserves_world(self):
        self.assertEqual(
            self._run(),
            ["stage", "checkpoint", "activate", "doctor", "commit", "cleanup"],
        )

    def test_recover_when_interrupted_between_two_renames(self):
        events = self._run(fail_at="after_old_moved")
        self.assertEqual(events[-2:], ["rollback", "cleanup"])

    def test_recover_post_swap_and_bad_readiness(self):
        for fault in ("activate", "readiness", "commit"):
            with self.subTest(fault=fault):
                self.assertIn("rollback", self._run(fail_at=fault))

    def test_precheckpoint_failure_does_not_touch_existing_files(self):
        for fault in ("stage", "checkpoint"):
            with self.subTest(fault=fault):
                self.assertNotIn("activate", self._run(fail_at=fault))


if __name__ == "__main__":
    unittest.main()
