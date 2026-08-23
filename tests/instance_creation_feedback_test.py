#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
for directory in (DASHBOARD, DATABASE):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from instance_creation_feedback import record_instance_creation_failure


class InstanceCreationFeedbackTest(unittest.TestCase):
    def test_customer_ui_prefers_explanatory_api_message(self):
        script = (ROOT / "dashboard/web/runtime-selector.js").read_text(encoding="utf-8")
        self.assertIn("data.message || data.error", script)

    def test_failure_reaches_audit_timeline_and_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            notices = []
            failure = {
                "code": "placement_unavailable",
                "reason": "agent heartbeat expired",
                "username": "aurora",
                "customer_id": "AURORA",
                "contract_id": "dayz-contract",
                "game": "dayz",
                "placement": {"region_id": "br"},
            }
            with patch("instance_creation_feedback.audit_customer_event") as audit:
                record_instance_creation_failure(
                    failure,
                    root=root,
                    backend=object(),
                    notify=lambda level, title, message: notices.append((level, title, message)),
                )

            audit.assert_called_once()
            queue = json.loads((root / "runtime/events/queue.json").read_text(encoding="utf-8"))
            self.assertEqual(queue[0]["type"], "INSTANCE_CREATION_FAILED")
            self.assertEqual(queue[0]["customer_id"], "AURORA")
            self.assertIn("agent heartbeat expired", queue[0]["message"])
            self.assertEqual(notices[0][0], "warning")


if __name__ == "__main__":
    unittest.main()
