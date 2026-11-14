"""Coverage never conflates a stopped game with no-drain continuity proof."""
from __future__ import annotations
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader(
    "dsm928_coverage", str(ROOT / "update-manager/game-uptime-coverage.py")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
coverage = importlib.util.module_from_spec(spec)
loader.exec_module(coverage)

MINECRAFT = "capivara-instance-cli-000001-minecraft-005.service"
DAYZ = "capivara-instance-cli-000001-dayz-001.service"


def observation(unit, pid=4210, started=5151, verified=True):
    return {"unit": unit, "identity_verified": verified,
            "main_pid": pid, "start_stamp": started}


def inventory(*rows):
    return {"units": list(rows), "managed_active_units": len(rows)}


class OperationalCoverageTests(unittest.TestCase):
    def test_both_active_and_verified_is_rehearsal_candidate_only(self):
        result = coverage.assess(
            [MINECRAFT, DAYZ],
            inventory(observation(MINECRAFT, 2000, 4000),
                      observation(DAYZ, 3000, 5000)))
        self.assertTrue(result["verified_for_disposable_rehearsal"])
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertEqual(result["scope"],
                         "read_only_current_process_inventory_not_continuous_uptime")

    def test_minecraft_stopped_blocks_even_if_dayz_healthy(self):
        result = coverage.assess(
            [MINECRAFT, DAYZ], inventory(observation(DAYZ)))
        self.assertFalse(result["verified_for_disposable_rehearsal"])
        self.assertEqual(result["missing_active_units"], [MINECRAFT])
        self.assertIn("expected_active_service_not_running", result["blockers"])

    def test_caller_must_declare_both_game_families(self):
        absent = coverage.assess(None, inventory(observation(DAYZ)))
        self.assertFalse(absent["verified_for_disposable_rehearsal"])
        self.assertIn("expected_active_units_not_declared", absent["blockers"])
        only_dayz = coverage.assess([DAYZ], inventory(observation(DAYZ)))
        self.assertFalse(only_dayz["verified_for_disposable_rehearsal"])
        self.assertIn("expected_minecraft_service_missing", only_dayz["blockers"])

    def test_unexpected_service_and_duplicate_inventory_block(self):
        third = "capivara-instance-cli-000002-dayz-001.service"
        result = coverage.assess([MINECRAFT, DAYZ],
                                 inventory(observation(MINECRAFT),
                                           observation(DAYZ), observation(third)))
        self.assertIn(third, result["unexpected_active_units"])
        self.assertFalse(result["verified_for_disposable_rehearsal"])
        duplicate = coverage.assess([MINECRAFT, DAYZ],
                                    inventory(observation(MINECRAFT),
                                              observation(MINECRAFT),
                                              observation(DAYZ)))
        self.assertIn("active_inventory_duplicate_unit", duplicate["blockers"])

    def test_invalid_identity_and_missing_timestamp_block(self):
        for row in (
            observation(MINECRAFT, pid=0),
            observation(MINECRAFT, started=0),
            observation(MINECRAFT, pid=True),
            observation(MINECRAFT, verified=False),
        ):
            with self.subTest(row=row):
                outcome = coverage.assess([MINECRAFT, DAYZ],
                                          inventory(row, observation(DAYZ)))
                self.assertFalse(outcome["verified_for_disposable_rehearsal"])
                self.assertIn(MINECRAFT, outcome["unverified_units"])

    def test_inventory_error_or_mismatched_count_blocks(self):
        for data in (
            {"inventory_error": "systemctl inaccessible", "units": []},
            {"units": [observation(MINECRAFT), observation(DAYZ)],
             "managed_active_units": 1},
            None,
        ):
            with self.subTest(data=data):
                self.assertFalse(
                    coverage.assess([MINECRAFT, DAYZ], data)[
                        "verified_for_disposable_rehearsal"
                    ])

    def test_invalid_or_duplicate_expected_names_block(self):
        expected_sets = [
            [MINECRAFT, MINECRAFT, DAYZ],
            [MINECRAFT, "not-a-systemd-unit"],
            "invalid",
        ]
        for names in expected_sets:
            with self.subTest(names=names):
                outcome = coverage.assess(
                    names, inventory(observation(MINECRAFT), observation(DAYZ)))
                self.assertFalse(outcome["verified_for_disposable_rehearsal"])
                self.assertIn("invalid_expected_active_unit_set",
                              outcome["blockers"])


if __name__ == "__main__":
    unittest.main()
