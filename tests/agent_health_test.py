#!/usr/bin/env python3

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.agent_health import derive_agent_health, utc_timestamp


class AgentHealthTest(unittest.TestCase):
    def test_health_transitions_are_derived_from_last_seen(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            derive_agent_health(utc_timestamp(now - timedelta(seconds=30)), now=now),
            "online",
        )
        self.assertEqual(
            derive_agent_health(utc_timestamp(now - timedelta(seconds=70)), now=now),
            "degraded",
        )
        self.assertEqual(
            derive_agent_health(utc_timestamp(now - timedelta(seconds=130)), now=now),
            "offline",
        )

    def test_missing_heartbeat_is_offline(self):
        self.assertEqual(derive_agent_health(None), "offline")


if __name__ == "__main__":
    unittest.main()
