#!/usr/bin/env python3
"""Offline, read-only world-preservation audit tests."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "minecraft_modpack_world_audit.py"


class WorldPreservationAuditTest(unittest.TestCase):
    def invoke(self, root: Path, mode: str, baseline: Path):
        return subprocess.run(
            [sys.executable, str(AUDIT), "--instance-root", str(root),
             mode, str(baseline)],
            capture_output=True, text=True, check=False,
        )

    def test_custom_world_overworld_nether_end_and_playerdata_all_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            game = base / "instance" / "game-data"
            game.mkdir(parents=True)
            baseline = base / "outside-world-baseline.json"
            (game / "server.properties").write_text(
                "max-players=30\nlevel-name=My Survival\n", encoding="utf-8")
            files = {}
            for relative in (
                "My Survival/level.dat",
                "My Survival/region/r.0.0.mca",
                "My Survival/playerdata/uuid.dat",
                "My Survival/advancements/uuid.json",
                "My Survival/stats/uuid.json",
                "My Survival_nether/DIM-1/region/r.0.0.mca",
                "My Survival_the_end/DIM1/region/r.0.0.mca",
                "dimensions/example/custom/region/r.1.0.mca",
            ):
                item = game / relative
                item.parent.mkdir(parents=True, exist_ok=True)
                item.write_bytes(("PLAYER DATA " + relative).encode())
                files[relative] = item.read_bytes()

            created = self.invoke(game, "--save-baseline", baseline)
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertTrue(baseline.is_file())
            # A modpack update is allowed to replace managed mods and settings,
            # but cannot change world chunks or player progress.
            (game / "mods").mkdir()
            (game / "mods" / "new-mod.jar").write_bytes(b"UPDATED JAR")
            (game / "config").mkdir()
            (game / "config" / "mod.toml").write_text("new-config=true")
            unchanged = self.invoke(game, "--compare-baseline", baseline)
            self.assertEqual(unchanged.returncode, 0, unchanged.stdout + unchanged.stderr)
            self.assertIn("WORLD_UNCHANGED", unchanged.stdout)
            for relative, expected in files.items():
                self.assertEqual((game / relative).read_bytes(), expected)

            # Prove the audit catches a re-generated region instead of merely
            # comparing filenames and file sizes.
            target = game / "My Survival" / "region" / "r.0.0.mca"
            original = target.read_bytes()
            target.write_bytes(b"X" * len(original))
            modified = self.invoke(game, "--compare-baseline", baseline)
            self.assertEqual(modified.returncode, 1)
            self.assertIn("WORLD_PRESERVATION_FAILED", modified.stdout)
            self.assertIn("modified files:", modified.stdout)
            target.write_bytes(original)

            # An upgrade must not delete player inventories/progress or add a
            # replacement world folder, even when the old region is untouched.
            progress = game / "My Survival" / "playerdata" / "uuid.dat"
            progress.unlink()
            missing = self.invoke(game, "--compare-baseline", baseline)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("missing files:", missing.stdout)
            progress.write_bytes(files["My Survival/playerdata/uuid.dat"])

            new_chunk = game / "My Survival" / "region" / "r.99.99.mca"
            new_chunk.write_bytes(b"UNEXPECTED_REGENERATION")
            added = self.invoke(game, "--compare-baseline", baseline)
            self.assertEqual(added.returncode, 1)
            self.assertIn("added files:", added.stdout)
            new_chunk.unlink()
            self.assertEqual(
                self.invoke(game, "--compare-baseline", baseline).returncode, 0)

    def test_audit_cannot_write_baseline_inside_live_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "instance"
            root.mkdir()
            result = self.invoke(root, "--save-baseline", root / "baseline.json")
            self.assertEqual(result.returncode, 2)
            self.assertFalse((root / "baseline.json").exists())

    def test_world_name_change_is_distinguished_from_file_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            game = base / "instance"
            game.mkdir()
            props = game / "server.properties"
            props.write_text("level-name=Survival\n")
            world = game / "Survival" / "level.dat"
            world.parent.mkdir()
            world.write_bytes(b"CURRENT WORLD")
            baseline = base / "baseline.json"
            self.assertEqual(self.invoke(game, "--save-baseline", baseline).returncode, 0)
            props.write_text("level-name=BrandNewWorld\n")
            result = self.invoke(game, "--compare-baseline", baseline)
            self.assertEqual(result.returncode, 2)
            self.assertIn("world name changed", result.stderr)


if __name__ == "__main__":
    unittest.main()
