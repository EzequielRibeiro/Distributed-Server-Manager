#!/usr/bin/env python3

import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"

sys.path.insert(0, str(DASHBOARD))
sys.path.insert(0, str(DATABASE))

from agent_ports_api import _json_ready


class AgentApiJsonSerializationTest(unittest.TestCase):
    def test_temporal_values_are_normalized_recursively(self):
        timestamp = datetime(2026, 8, 22, 20, 10, 15, tzinfo=timezone.utc)
        payload = {
            "agent": {
                "last_heartbeat": timestamp,
                "registered_on": date(2026, 8, 22),
            },
            "ranges": [
                {"updated_at": timestamp},
            ],
            "history": (timestamp,),
        }

        normalized = _json_ready(payload)

        self.assertEqual(
            normalized["agent"]["last_heartbeat"],
            "2026-08-22T20:10:15+00:00",
        )
        self.assertEqual(normalized["agent"]["registered_on"], "2026-08-22")
        self.assertEqual(normalized["ranges"][0]["updated_at"], "2026-08-22T20:10:15+00:00")
        self.assertEqual(normalized["history"], ["2026-08-22T20:10:15+00:00"])
        json.dumps(normalized)


if __name__ == "__main__":
    unittest.main()
