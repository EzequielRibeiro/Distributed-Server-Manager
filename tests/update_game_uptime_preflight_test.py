"""Read-only no-drain impact reporting for two real-shaped managed game units."""
import importlib.util
import hashlib
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

    def test_matching_contract_requires_verified_systemd_pin_not_boolean(self):
        self.write("dashboard/web/style.css", "old", "new")
        for root in (self.installed, self.target):
            supervisor = root / module.compatibility.SUPERVISOR_RELATIVE
            supervisor.parent.mkdir(parents=True, exist_ok=True)
            supervisor.write_text("same supervisor")
        contract = {"protocol": "v1", "schema": "22",
                    "controller_api": "v2", "agent_api": "v2"}
        versions = self.installed.parent / "versions"
        versions.mkdir()
        digest = hashlib.sha256(b"pinned fixture").hexdigest()
        pinned = versions / ("console-supervisor-" + digest + ".py")
        pinned.write_bytes(b"pinned fixture")
        def observed(unit):
            if "minecraft" not in unit:
                return {"main_pid": 12345, "start_stamp": 666}
            return {"main_pid": 54321, "start_stamp": 777,
                    "exec": "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 " +
                            str(pinned) + " --socket /tmp/fixture.sock -- /usr/bin/sleep 15 ;",
                    "fragment": "/etc/systemd/system/" + unit}
        kwargs = dict(list_units=lambda: self.units, inspect=observed,
                      controller_contract=contract, agent_contract=contract)
        blocked = module.preflight(self.installed, self.target, **kwargs,
                                   supervisor_pinned=True)
        self.assertFalse(blocked["no_drain_compatibility_verified"])
        self.assertIn("pinned_supervisor_evidence_missing",
                      blocked["supervisor_pin_evidence"]["blockers"])
        candidate = module.preflight(
            self.installed, self.target, **kwargs,
            supervisor_versions_dir=versions, supervisor_expected_sha256=digest)
        self.assertTrue(candidate["supervisor_pin_evidence"]["verified"])
        self.assertTrue(candidate["no_drain_compatibility_verified"])
        self.assertFalse(candidate["live_no_drain_authorized"])
        self.assertTrue(candidate["current_updater_drains_active_games"])

    def test_pid_change_between_inventory_and_supervisor_inspection_blocks(self):
        self.write("dashboard/web/style.css", "old", "new")
        versions = self.installed.parent / "versions"
        versions.mkdir()
        digest = hashlib.sha256(b"supervisor").hexdigest()
        path = versions / ("console-supervisor-" + digest + ".py")
        path.write_bytes(b"supervisor")
        for root in (self.installed, self.target):
            source = root / module.compatibility.SUPERVISOR_RELATIVE
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("supervisor")
        calls = {"minecraft": 0}
        def observed(unit):
            if "minecraft" not in unit:
                return {"main_pid": 12345, "start_stamp": 666}
            calls["minecraft"] += 1
            return {"main_pid": 532 if calls["minecraft"] == 1 else 533,
                    "start_stamp": 777,
                    "exec": "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 " +
                            str(path) + " --socket /tmp/test.sock -- /usr/bin/sleep 15 ;",
                    "fragment": "/etc/systemd/system/" + unit}
        contract = {"protocol": "v1", "schema": "22",
                    "controller_api": "v2", "agent_api": "v2"}
        result = module.preflight(
            self.installed, self.target, list_units=lambda: self.units, inspect=observed,
            controller_contract=contract, agent_contract=contract,
            supervisor_versions_dir=versions, supervisor_expected_sha256=digest)
        self.assertFalse(result["supervisor_pin_evidence"]["verified"])
        self.assertTrue(any("process identity changed" in blocker
                            for blocker in result["supervisor_pin_evidence"]["blockers"]))
        self.assertFalse(result["no_drain_compatibility_verified"])
        self.assertFalse(result["live_no_drain_authorized"])


    def test_operational_coverage_never_accepts_stopped_minecraft(self):
        self.write("dashboard/web/style.css", "old", "new")
        actual = [unit for unit in self.units if "dayz" in unit]
        result = module.preflight(
            self.installed, self.target,
            list_units=lambda: actual,
            inspect=lambda unit: {"main_pid": 3456, "start_stamp": 7890},
            expected_active_units=self.units,
        )
        self.assertFalse(result["no_drain_operational_coverage_verified"])
        self.assertEqual(
            result["operational_coverage"]["missing_active_units"],
            [next(unit for unit in self.units if "minecraft" in unit)],
        )
        self.assertFalse(result["live_no_drain_authorized"])

    def test_operational_coverage_requires_explicit_full_active_baseline(self):
        self.write("dashboard/web/style.css", "old", "new")
        inspect = lambda unit: {"main_pid": 3456 if "dayz" in unit else 4567,
                                "start_stamp": 7890 if "dayz" in unit else 8901}
        unknown = module.preflight(
            self.installed, self.target, list_units=lambda: self.units,
            inspect=inspect,
        )
        self.assertFalse(unknown["no_drain_operational_coverage_verified"])
        confirmed = module.preflight(
            self.installed, self.target, list_units=lambda: self.units,
            inspect=inspect, expected_active_units=self.units,
        )
        self.assertTrue(confirmed["no_drain_operational_coverage_verified"])
        self.assertFalse(confirmed["live_no_drain_authorized"])
        self.assertTrue(confirmed["current_updater_drains_active_games"])

if __name__ == "__main__":
    unittest.main()
