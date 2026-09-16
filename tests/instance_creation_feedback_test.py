#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
for directory in (DASHBOARD, DATABASE):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from instance_creation_feedback import (
    record_instance_creation_failure,
    record_instance_creation_success,
)


class InstanceCreationFeedbackTest(unittest.TestCase):
    def test_customer_ui_prefers_explanatory_api_message(self):
        script = (ROOT / "dashboard/web/runtime-selector.js").read_text(encoding="utf-8")
        self.assertIn("data.message || data.error", script)

    def test_placement_failure_reaches_audit_timeline_and_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            notices = []
            failure = {
                "code": "placement_unavailable",
                "reason": "no eligible Agent is available for placement",
                "placement_reason": "requested_region_unavailable",
                "username": "aurora",
                "customer_id": "AURORA",
                "contract_id": "dayz-contract",
                "game": "dayz",
                "runtime_id": "dayz.stable",
                "region_id": "br",
                "agents_evaluated": 2,
                "technical_rejections": {"agent-1": ["unsupported_runtime_profile"]},
                "placement": {"region_id": "br"},
            }
            incident = {
                "id": "customer-health-1",
                "level": "WARNING",
                "transition": "OPEN",
            }
            with patch("instance_creation_feedback.audit_customer_event") as audit, \
                 patch("instance_creation_feedback._record_placement_incident", return_value=incident):
                record_instance_creation_failure(
                    failure,
                    root=root,
                    backend=object(),
                    notify=lambda level, title, message: notices.append((level, title, message)),
                )

            audit.assert_called_once()
            queue = json.loads((root / "runtime/events/queue.json").read_text(encoding="utf-8"))
            self.assertEqual(queue[0]["type"], "CUSTOMER_INSTANCE_PLACEMENT_BLOCKED")
            self.assertEqual(queue[0]["customer_id"], "AURORA")
            self.assertEqual(queue[0]["runtime_id"], "dayz.stable")
            self.assertEqual(queue[0]["reason"], "requested_region_unavailable")
            self.assertEqual(queue[0]["agents_evaluated"], 2)
            self.assertEqual(queue[0]["incident_id"], "customer-health-1")
            self.assertEqual(notices[0][0], "warning")
            self.assertEqual(notices[0][1], "Cliente impedido de criar instância")

    def test_duplicate_placement_incident_does_not_spam_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            notices = []
            failure = {
                "code": "placement_unavailable",
                "customer_id": "AURORA",
                "game": "minecraft",
                "runtime_id": "minecraft.java.neoforge",
                "placement_reason": "requested_region_unavailable",
                "placement": {"region_id": "br-sp"},
            }
            incident = {
                "id": "customer-health-1",
                "level": "WARNING",
                "transition": "UNCHANGED",
            }
            with patch("instance_creation_feedback.audit_customer_event"), \
                 patch("instance_creation_feedback._record_placement_incident", return_value=incident):
                record_instance_creation_failure(
                    failure,
                    root=Path(temporary),
                    backend=object(),
                    notify=lambda level, title, message: notices.append((level, title, message)),
                )
        self.assertEqual(notices, [])

    def test_success_resolves_matching_placement_incident(self):
        with tempfile.TemporaryDirectory() as temporary:
            notices = []
            service = MagicMock()
            service.recovered.return_value = {
                "id": "customer-health-1",
                "state": "RESOLVED",
            }
            success = {
                "username": "aurora",
                "customer_id": "AURORA",
                "contract_id": "dayz-contract",
                "game": "dayz",
                "runtime_id": "dayz.stable",
                "placement": {"region_id": "br"},
                "instance_id": "srv-001",
            }
            with patch("instance_creation_feedback._customer_context", return_value={
                "id": "42",
                "controller_id": "controller-a",
                "name": "Aurora",
                "customer_code": "AURORA",
            }), patch("instance_creation_feedback.CustomerHealthService", return_value=service):
                record_instance_creation_success(
                    success,
                    root=Path(temporary),
                    backend=object(),
                    notify=lambda level, title, message: notices.append((level, title, message)),
                )

            service.recovered.assert_called_once()
            queue = json.loads((Path(temporary) / "runtime/events/queue.json").read_text(encoding="utf-8"))
            self.assertEqual(queue[0]["type"], "CUSTOMER_ERROR_RESOLVED")
            self.assertEqual(queue[0]["instance_id"], "srv-001")
            self.assertEqual(notices[0][0], "info")


if __name__ == "__main__":
    unittest.main()
