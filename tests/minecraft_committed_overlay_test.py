#!/usr/bin/env python3
"""Regression: installer overlay cannot undo a committed NeoForge migration."""
import importlib.util
import json
import os
import pwd
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
MODULE = ROOT / "agents/linux/privileged/materialize_instance.py"
spec = importlib.util.spec_from_file_location("capivara_overlay_test_module", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class NeoForgeCommittedOverlayTest(unittest.TestCase):
    def test_overlay_preserves_launcher_but_updates_other_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            source=base/"install"
            state=base/"instance"
            target=state/"runtime"
            source.mkdir()
            target.mkdir(parents=True)
            (state/".dsm").mkdir()
            (state/".dsm/minecraft-serverpack-migration.json").write_text(
                json.dumps({"phase":"committed","target_loader_version":"26.1.2.109"}))
            for name in ("capivara-launch.args","run.sh","run.bat"):
                (source/name).write_text("26.1.2.94")
                (target/name).write_text("26.1.2.109")
            (source/"eula.txt").write_text("eula=true")
            account=pwd.getpwuid(os.getuid())
            mod._seed_directory(source,target,account,overlay=True)
            for name in ("capivara-launch.args","run.sh","run.bat"):
                self.assertEqual((target/name).read_text(),"26.1.2.109")
            self.assertEqual((target/"eula.txt").read_text(),"eula=true")

    def test_uncommitted_overlay_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            source=base/"install"
            target=base/"instance/runtime"
            source.mkdir()
            target.mkdir(parents=True)
            (source/"run.sh").write_text("old")
            (target/"run.sh").write_text("new")
            mod._seed_directory(source,target,pwd.getpwuid(os.getuid()),overlay=True)
            self.assertEqual((target/"run.sh").read_text(),"old")

if __name__=="__main__":
    unittest.main()
