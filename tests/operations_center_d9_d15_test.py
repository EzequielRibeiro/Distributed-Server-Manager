#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
for value in (str(ROOT), str(DASHBOARD), str(DATABASE)):
    if value not in sys.path:
        sys.path.insert(0, value)

from operations_center_service import OperationsCenterService


class _FakeAutomation:
    def __init__(self):
        self.saved = None

    def initialize(self):
        return None

    def put_rule(self, raw, *, requested_by=None):
        self.saved = (raw, requested_by)
        return {"rule": raw, "changed": True}


class OperationsCenterD9D15Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web = ROOT / "dashboard" / "web"
        cls.html = (web / "operations.html").read_text(encoding="utf-8")
        cls.js = (web / "operations.js").read_text(encoding="utf-8")
        cls.index = (web / "index.html").read_text(encoding="utf-8")
        cls.sidebar = (web / "components" / "sidebar.html").read_text(encoding="utf-8")
        cls.server = (ROOT / "dashboard" / "server_part14.py").read_text(encoding="utf-8")
        cls.service = (ROOT / "systemd" / "dsm-dashboard.service").read_text(encoding="utf-8")

    def test_d9_operations_center_has_all_administrative_views(self):
        for token in ('id="incidents"', 'id="alerts"', 'id="events"', 'id="schedules"', 'id="logs"', 'id="controller-backup"'):
            self.assertIn(token, self.html)
        self.assertIn("/api/operations?view=summary", self.js)
        self.assertIn("/api/backups?kind=health", self.js)

    def test_d10_incident_engine_correlates_problem_until_resolution(self):
        service = object.__new__(OperationsCenterService)
        events = [
            {"event_id": "1", "correlation_id": "install-42", "event_type": "INSTALL_REQUESTED", "severity": "info", "occurred_at": "2026-08-22T14:00:00Z", "source": "installer", "agent_id": "agent-01", "instance_id": None},
            {"event_id": "2", "correlation_id": "install-42", "event_type": "STEAM_AUTH_REQUIRED", "severity": "critical", "occurred_at": "2026-08-22T14:01:00Z", "source": "steam", "agent_id": "agent-01", "instance_id": None},
            {"event_id": "3", "correlation_id": "install-42", "event_type": "STEAM_AUTH_SUCCEEDED", "severity": "info", "occurred_at": "2026-08-22T14:05:00Z", "source": "steam", "agent_id": "agent-01", "instance_id": None},
            {"event_id": "4", "correlation_id": "install-42", "event_type": "INSTALL_COMPLETED", "severity": "info", "occurred_at": "2026-08-22T14:15:00Z", "source": "installer", "agent_id": "agent-01", "instance_id": None},
        ]
        incidents = service._incident_groups(events)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["incident_id"], "install-42")
        self.assertEqual(incidents[0]["severity"], "critical")
        self.assertEqual(incidents[0]["status"], "resolved")
        self.assertEqual(incidents[0]["event_count"], 4)
        self.assertEqual(incidents[0]["resolved_at"], "2026-08-22T14:15:00Z")

    def test_d11_timeline_exposes_correlation_and_alert_actions(self):
        self.assertIn("correlation_id", self.js)
        self.assertIn("incident-timeline", self.js)
        self.assertIn("acknowledge_alert", self.js)
        self.assertIn("resolve_alert", self.js)

    def test_d12_scheduler_execution_history_and_creation_are_available(self):
        self.assertIn("view=schedules", self.js)
        self.assertIn('id="schedule-rules"', self.html)
        self.assertIn('id="schedule-runs"', self.html)
        self.assertIn('id="schedule-new"', self.html)
        self.assertIn('id="schedule-form"', self.html)
        self.assertIn("create_schedule", self.js)
        self.assertIn("set_schedule_enabled", self.js)
        self.assertIn('return "0 * * * *"', self.js)
        service_source = (ROOT / "dashboard" / "operations_center_service.py").read_text(encoding="utf-8")
        self.assertIn("list_runs", service_source)
        self.assertIn("create_schedule", service_source)

    def test_d12_administrative_schedule_is_persisted_as_canonical_rule(self):
        service = object.__new__(OperationsCenterService)
        service.events = type("Events", (), {"initialize": lambda self: None})()
        service.alerts = type("Alerts", (), {"initialize": lambda self: None})()
        service.automation = _FakeAutomation()
        result = service.create_schedule(
            {
                "name": "Doctor noturno",
                "scope": "controller",
                "action": "infrastructure_doctor",
                "expression": "0 3 * * *",
                "timezone": "America/Sao_Paulo",
                "enabled": True,
            },
            user={"role": "admin", "username": "admin"},
        )
        raw, requested_by = service.automation.saved
        self.assertTrue(result["changed"])
        self.assertTrue(raw["rule_id"].startswith("admin-schedule-"))
        self.assertEqual(raw["trigger"]["type"], "schedule")
        self.assertEqual(raw["trigger"]["expression"], "0 3 * * *")
        self.assertEqual(raw["trigger"]["timezone"], "America/Sao_Paulo")
        self.assertEqual(raw["actions"][0]["type"], "administrative")
        self.assertEqual(raw["actions"][0]["operation"], "infrastructure_doctor")
        self.assertEqual(requested_by, "admin")

    def test_d12_agent_schedule_requires_agent_target(self):
        service = object.__new__(OperationsCenterService)
        service.events = type("Events", (), {"initialize": lambda self: None})()
        service.alerts = type("Alerts", (), {"initialize": lambda self: None})()
        service.automation = _FakeAutomation()
        with self.assertRaisesRegex(ValueError, "Agent é obrigatório"):
            service.create_schedule(
                {
                    "name": "Agent health",
                    "scope": "agent",
                    "action": "agent_health_check",
                    "expression": "*/15 * * * *",
                    "timezone": "UTC",
                },
                user={"role": "admin"},
            )

    def test_d13_operational_log_history_is_structured(self):
        self.assertIn("view=logs", self.js)
        self.assertIn('id="log-list"', self.html)
        self.assertIn("event_type", self.js)

    def test_d14_dashboard_shows_active_incidents(self):
        self.assertIn('id="active-incidents-card"', self.index)
        self.assertIn('id="active-incidents-count"', self.index)
        self.assertIn('/operations.html#incidents', self.index)

    def test_d15_navigation_and_entrypoint_are_integrated(self):
        self.assertIn('operations.html#alerts', self.sidebar)
        self.assertIn('operations.html#events', self.sidebar)
        self.assertIn('operations.html#schedules', self.sidebar)
        self.assertIn('operations.html#logs', self.sidebar)
        self.assertIn('OPERATIONS_PATH', self.server)
        self.assertIn('dashboard/server_part14.py', self.service)
        self.assertNotIn('index.html#alerts-component', self.sidebar)
        self.assertNotIn('index.html#events-list', self.sidebar)
        self.assertNotIn('index.html#scheduler-list', self.sidebar)


if __name__ == "__main__":
    unittest.main()
