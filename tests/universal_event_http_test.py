#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from universal_event_http import EVENTS_PATH, dispatch_universal_event_get, dispatch_universal_event_post


class UniversalEventHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        self.admin = {"username": "admin", "role": "admin"}
        self.customer = {"username": "customer", "role": "customer"}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_admin_can_publish_list_and_show(self):
        status, result = dispatch_universal_event_post(EVENTS_PATH, {
            "event_id": "http-event",
            "event_type": "INFRASTRUCTURE_RECONCILED",
            "source": "controller.infrastructure",
            "severity": "info",
            "data": {"repairs": 1},
        }, user=self.admin, backend=self.backend)
        self.assertEqual(status, 201)
        self.assertEqual(result["event"]["event_id"], "http-event")

        status, listing = dispatch_universal_event_get(EVENTS_PATH, "type=INFRASTRUCTURE_RECONCILED&limit=10", user=self.admin, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(listing["count"], 1)

        status, event = dispatch_universal_event_get(EVENTS_PATH, "event_id=http-event", user=self.admin, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(event["data"], {"repairs": 1})

    def test_customer_is_forbidden(self):
        status, _ = dispatch_universal_event_get(EVENTS_PATH, "", user=self.customer, backend=self.backend)
        self.assertEqual(status, 403)
        status, _ = dispatch_universal_event_post(EVENTS_PATH, {
            "event_type": "TEST_EVENT", "source": "test",
        }, user=self.customer, backend=self.backend)
        self.assertEqual(status, 403)

    def test_invalid_event_returns_controlled_error(self):
        status, result = dispatch_universal_event_post(EVENTS_PATH, {
            "event_type": "bad type", "source": "test",
        }, user=self.admin, backend=self.backend)
        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
