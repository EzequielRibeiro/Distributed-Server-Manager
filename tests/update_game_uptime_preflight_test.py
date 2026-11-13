"""Read-only no-drain impact reporting for two real-shaped managed game units."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("game_uptime_preflight", str(ROOT/"update-manager/game-uptime-preflight.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class UpdatePreflightTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.installed = Path(tmp.name)/"installed"
        self.target = Path(tmp.name)/"target"
        self.installed.mkdir()
        self.target.mkdir()
        self.units = ["capivara-instance-minecraft-005.service", "capivara-instance-dayz-001.service"]

    def write(self, path, before, after):
        for root, value in ((self.installed,before),(self.target,after)):
            file = root/path
            file.parent.mkdir(parents=True,exist_ok=True)
            file.write_text(value)

    def inspect(self, unit):
        if "minecraft" in unit:
            raise module.reporter.guard.GateError(
                "game ExecStart points into replaceable DSM control-plane paths")
        return {"main_pid": 12345}

    def result(self):
        return module.preflight(self.installed,self.target,list_units=lambda: self.units,
                                inspect=self.inspect)

    def test_cosmetic_change_still_lists_exact_stop_and_restart_actions(self):
        self.write("dashboard/web/style.css", "old", "new")
        state = self.result()
        self.assertEqual(state["classification"],"review_only")
        self.assertFalse(state["live_no_drain_authorized"])
        self.assertTrue(state["current_updater_drains_active_games"])
        self.assertEqual([row["unit"] for row in state["planned_game_actions"]],sorted(self.units))
        self.assertTrue(all(row["action"] == "stop_and_restart" for row in
                            state["planned_game_actions"]))
        minecraft = next(x for x in state["units"] if "minecraft" in x["unit"])
        dayz = next(x for x in state["units"] if "dayz" in x["unit"])
        self.assertFalse(minecraft["no_drain_candidate"])
        self.assertTrue(dayz["no_drain_candidate"])
        self.assertFalse(dayz["no_drain_authorized"])

    def test_runtime_change_requires_maintenance_even_for_safe_unit(self):
        self.write("agents/linux/runtime/agent.py","old","new")
        state=self.result()
        self.assertEqual(state["classification"],"maintenance_required")
        self.assertTrue(state["requires_game_drain"])
        self.assertFalse(any(x["no_drain_candidate"] for x in state["units"]))

    def test_bad_inventory_fails_closed(self):
        self.write("dashboard/web/style.css","old","new")
        state=module.preflight(self.installed,self.target,list_units=lambda:["invalid.service"])
        self.assertEqual(state["classification"],"blocked")
        self.assertTrue(state["requires_game_drain"])
        self.assertFalse(state["live_no_drain_authorized"])
        self.assertEqual(state["planned_game_actions"],[])

    def test_symlink_fails_closed(self):
        (self.target/"escape").symlink_to(self.installed)
        state=self.result()
        self.assertEqual(state["classification"],"blocked")
        self.assertTrue(state["requires_game_drain"])

    def test_zero_active_units_still_never_authorizes_no_drain(self):
        self.write("dashboard/web/style.css","old","new")
        state=module.preflight(self.installed,self.target,list_units=lambda: [],
                               inspect=self.inspect)
        self.assertEqual(state["classification"],"review_only")
        self.assertFalse(state["live_no_drain_authorized"])
        self.assertEqual(state["units"],[])


    def test_preflight_embeds_fail_closed_compatibility_gate(self):
        self.write("dashboard/web/style.css", "old", "new")
        state = self.result()
        self.assertFalse(state["no_drain_compatibility_verified"])
        self.assertIn("controller_agent_contract_missing", state["compatibility_gate"]["blockers"])
        self.assertFalse(any(row["no_drain_compatibility_verified"] for row in state["units"]))
        self.assertFalse(state["live_no_drain_authorized"])

    def test_matching_contract_requires_supervisor_isolation(self):
        self.write("dashboard/web/style.css", "old", "new")
        for root in (self.installed, self.target):
            supervisor = root / module.compatibility.SUPERVISOR_RELATIVE
            supervisor.parent.mkdir(parents=True, exist_ok=True)
            supervisor.write_text("same supervisor")
        contract = {"protocol": "v1", "schema": "22",
                    "controller_api": "v2", "agent_api": "v2"}
        blocked = module.preflight(self.installed, self.target,
                    list_units=lambda: self.units, inspect=self.inspect,
                    controller_contract=contract, agent_contract=contract)
        self.assertIn("minecraft_supervisor_lifecycle_not_isolated",
                      blocked["compatibility_gate"]["blockers"])
        candidate = module.preflight(self.installed, self.target,
                    list_units=lambda: self.units, inspect=self.inspect,
                    controller_contract=contract, agent_contract=contract,
                    supervisor_pinned=True)
        self.assertTrue(candidate["no_drain_compatibility_verified"])
        self.assertFalse(candidate["live_no_drain_authorized"])
        self.assertTrue(candidate["current_updater_drains_active_games"])

if __name__ == "__main__":
    unittest.main()
