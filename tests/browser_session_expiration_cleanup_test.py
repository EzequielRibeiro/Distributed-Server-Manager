#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
sys.path.insert(0, str(DASHBOARD))

import controller_session


class BrowserSessionExpirationCleanupTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        controller_session.SESSION_FILE = Path(self.tempdir.name) / "sessions.json"
        controller_session._sessions.clear()
        controller_session._loaded = False

    def tearDown(self):
        controller_session._sessions.clear()
        controller_session._loaded = False
        self.tempdir.cleanup()

    def test_registry_reload_removes_expired_entry_without_cookie(self):
        now = int(time.time())
        controller_session.SESSION_FILE.write_text(
            json.dumps(
                {
                    "expired-hash": {
                        "username": "admin",
                        "role": "admin",
                        "area": "controller",
                        "created_at": now - 60,
                        "expires_at": now - 1,
                    },
                    "valid-hash": {
                        "username": "aurora",
                        "role": "customer",
                        "area": "customer",
                        "created_at": now,
                        "expires_at": now + 60,
                    },
                }
            ),
            encoding="utf-8",
        )

        self.assertIsNone(controller_session.get_session(None))

        persisted = json.loads(
            controller_session.SESSION_FILE.read_text(encoding="utf-8")
        )
        self.assertNotIn("expired-hash", persisted)
        self.assertIn("valid-hash", persisted)

    def test_loaded_registry_prunes_all_expired_entries_when_cookie_is_absent(self):
        now = int(time.time())
        controller_session._sessions.update(
            {
                "expired-controller": {
                    "username": "admin",
                    "role": "admin",
                    "area": "controller",
                    "created_at": now - 60,
                    "expires_at": now - 1,
                },
                "expired-customer": {
                    "username": "aurora",
                    "role": "customer",
                    "area": "customer",
                    "created_at": now - 60,
                    "expires_at": now - 1,
                },
            }
        )
        controller_session._loaded = True
        controller_session._persist_sessions()

        self.assertIsNone(controller_session.get_session(None))
        self.assertEqual(controller_session._sessions, {})
        self.assertEqual(
            json.loads(controller_session.SESSION_FILE.read_text(encoding="utf-8")),
            {},
        )


if __name__ == "__main__":
    unittest.main()
