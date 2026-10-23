"""Fail-closed, read-only preflight update change classifier tests."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"update-manager"))
from importlib.machinery import SourceFileLoader

# Hyphenated helper path is intentionally used by the updater.
from importlib.util import spec_from_loader, module_from_spec
loader=SourceFileLoader("game_uptime_plan",str(ROOT/"update-manager/game-uptime-plan.py"))
spec=spec_from_loader(loader.name,loader)
plan=module_from_spec(spec)
loader.exec_module(plan)


class UptimeImpactTest(unittest.TestCase):
    def setUp(self):
        self.workspace=tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.installed=Path(self.workspace.name)/"installed"
        self.target=Path(self.workspace.name)/"target"
        self.installed.mkdir();self.target.mkdir()

    def put(self,path,old,new):
        for root,data in ((self.installed,old),(self.target,new)):
            p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)

    def test_runtime_change_requires_drain(self):
        self.put("agents/linux/runtime/agent.py","old","new")
        state=plan.analyze(self.installed,self.target)
        self.assertTrue(state["requires_game_drain"])
        self.assertFalse(state["live_no_drain_authorized"])

    def test_unit_change_requires_drain(self):
        self.put("systemd/capivara-instance@.service","old","new")
        self.assertTrue(plan.analyze(self.installed,self.target)["requires_game_drain"])

    def test_safe_cosmetic_candidate_never_authorizes_update(self):
        self.put("dashboard/web/style.css","old","new")
        state=plan.analyze(self.installed,self.target)
        self.assertEqual(state["classification"],"review_only")
        self.assertFalse(state["live_no_drain_authorized"])

    def test_unknown_file_is_critical(self):
        self.put("new-module/loader.py","old","new")
        self.assertTrue(plan.analyze(self.installed,self.target)["requires_game_drain"])

    def test_protected_runtime_state_is_excluded(self):
        self.put("runtime/hybrid-instance-storage/private/world.dat","one","two")
        state=plan.analyze(self.installed,self.target)
        self.assertEqual(state["changed_count"],0)

    def test_symlink_fails_closed(self):
        (self.target/"unsafe").symlink_to(self.installed)
        with self.assertRaises(ValueError):
            plan.analyze(self.installed,self.target)


if __name__=="__main__":
    unittest.main()
