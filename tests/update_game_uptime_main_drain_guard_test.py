"""#928 safety gate: main updater must never silently bypass draining.

This is an intentionally conservative regression contract. Until a separately
reviewed, fully homologated no-drain main path exists, preserve the explicit
service/game stop sequence before any backup or mutation. No host actions.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MainUpdaterDrainSafetyTests(unittest.TestCase):
    def test_main_still_quiesces_services_and_games_before_mutation(self):
        source = (ROOT / "update.sh").read_text(encoding="utf-8")
        start = source.index("\nmain() {")
        end = source.find("\n}\n", start)
        self.assertNotEqual(end, -1, "main() must have a closing brace")
        body = source[start:end]
        ordered = [
            "run_process_guard allow-managed",
            "capture_game_instance_state",
            "capture_service_state",
            "UPDATE_TRANSACTION_STARTED=1",
            "stop_services",
            "stop_game_instances",
            "run_process_guard",
            "create_staging",
            "apply_update",
        ]
        offsets = []
        cursor = 0
        for step in ordered:
            position = body.index(step, cursor)
            offsets.append(position)
            cursor = position + len(step)
        self.assertEqual(offsets, sorted(offsets))
        self.assertNotIn("live_no_drain_authorized=true", body)

    def test_no_drain_is_not_inferred_from_successful_preflight(self):
        source = (ROOT / "update.sh").read_text(encoding="utf-8")
        main = source[source.index("\nmain() {"):]
        self.assertIn("stop_game_instances", main)
        self.assertIn("stop_services", main)


if __name__ == "__main__":
    unittest.main()
