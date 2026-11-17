"""No-drain contract checks; disposable files only, no active services."""
from __future__ import annotations
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("game_uptime_compatibility", str(ROOT / "update-manager/game-uptime-compatibility.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
compat = importlib.util.module_from_spec(spec)
loader.exec_module(compat)
CONTRACT = {"protocol": "v1", "schema": "22", "controller_api": "v2", "agent_api": "v2"}


class NoDrainCompatibilityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsm928-contract-")
        self.addCleanup(tmp.cleanup)
        self.old, self.new = Path(tmp.name) / "old", Path(tmp.name) / "new"
        for root in (self.old, self.new):
            path = root / compat.SUPERVISOR_RELATIVE
            path.parent.mkdir(parents=True)
            path.write_text("stable supervisor")

    def assess(self, controller=CONTRACT, agent=CONTRACT, **kw):
        return compat.assess(self.old, self.new, controller, agent, **kw)

    def test_matching_contract_still_does_not_authorize_live_update(self):
        result = self.assess(supervisor_pinned=True)
        self.assertTrue(result["compatible_for_further_rehearsal"])
        self.assertFalse(result["live_no_drain_authorized"])

    def test_missing_contract_blocks(self):
        result = self.assess(None, CONTRACT, supervisor_pinned=True)
        self.assertIn("controller_agent_contract_missing", result["blockers"])

    def test_mismatch_blocks(self):
        result = self.assess(CONTRACT, {**CONTRACT, "schema": "23"}, supervisor_pinned=True)
        self.assertIn("controller_agent_schema_mismatch", result["blockers"])

    def test_unpinned_supervisor_blocks_even_when_unchanged(self):
        result = self.assess()
        self.assertIn("minecraft_supervisor_lifecycle_not_isolated", result["blockers"])

    def test_changed_supervisor_blocks_unpinned(self):
        (self.new / compat.SUPERVISOR_RELATIVE).write_text("new supervisor")
        result = self.assess()
        self.assertIn("minecraft_live_supervisor_replaceable", result["blockers"])

    def test_missing_supervisor_fails_closed(self):
        (self.new / compat.SUPERVISOR_RELATIVE).unlink()
        result = self.assess(supervisor_pinned=True)
        self.assertIn("minecraft_supervisor_unverifiable", result["blockers"])


if __name__ == "__main__":
    unittest.main()
