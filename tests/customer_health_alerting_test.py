#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from customer_health_repository import CustomerHealthRepository, incident_id_for
from customer_health_service import CustomerHealthService


class _Alerts:
    rows = []
    current = None

    def __init__(self, _backend):
        pass

    def get_alert(self, alert_id):
        if self.current and self.current.get("id") == alert_id:
            return dict(self.current)
        return None

    def open_alert(self, **kwargs):
        self.current = {
            "id": kwargs["alert_id"], "scope": kwargs["scope"], "controller_id": kwargs["controller_id"],
            "instance_id": kwargs.get("instance_id"), "rule_id": kwargs["rule_id"], "level": kwargs["level"],
            "state": "OPEN", "message": kwargs["message"], "action": "OPEN",
        }
        return dict(self.current)

    def alert_history(self, _alert_id):
        return [{"action": "OPEN"}]

    def acknowledge_alert(self, alert_id):
        value = dict(self.current); value["id"] = alert_id; value["state"] = "ACKNOWLEDGED"; return value

    def resolve_alert(self, alert_id):
        value = dict(self.current); value["id"] = alert_id; value["state"] = "RESOLVED"; self.current = value; return value

    def list_alerts(self, **_kwargs):
        return [dict(item) for item in self.rows]


class _Events:
    published = []

    def __init__(self, _backend):
        pass

    def publish(self, event):
        self.published.append(dict(event))
        return {"created": True, "event": event}


class CustomerHealthAlertingTest(unittest.TestCase):
    def setUp(self):
        _Alerts.current = None
        _Alerts.rows = []
        _Events.published = []
        self.backend = object()

    def test_dedupe_id_is_stable_and_does_not_expose_key(self):
        first = incident_id_for("customer:42:placement:contract-secret")
        second = incident_id_for("customer:42:placement:contract-secret")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("customer-health-"))
        self.assertNotIn("contract-secret", first)

    def test_repository_reuses_canonical_alert_store_and_filters_customer_scope(self):
        _Alerts.rows = [
            {"id": "a", "scope": "customer:42", "controller_id": "controller-a", "level": "ERROR", "state": "OPEN"},
            {"id": "b", "scope": "agent", "controller_id": "controller-a", "level": "CRITICAL", "state": "OPEN"},
            {"id": "c", "scope": "customer:99", "controller_id": "controller-a", "level": "WARNING", "state": "OPEN"},
        ]
        with patch("customer_health_repository.AlertRepository", _Alerts):
            repo = CustomerHealthRepository(self.backend)
            rows = repo.list_incidents(customer_id="42", controller_id="controller-a")
        self.assertEqual([row["id"] for row in rows], ["a"])
        self.assertEqual(rows[0]["customer_id"], "42")

    def test_failure_opens_incident_and_publishes_sanitized_customer_event(self):
        with patch("customer_health_repository.AlertRepository", _Alerts), \
             patch("customer_health_service.UniversalEventRepository", _Events):
            service = CustomerHealthService(self.backend)
            incident = service.failure(
                customer_id="42",
                controller_id="controller-a",
                dedupe_key="placement:42:contract-1",
                event_type="CUSTOMER_PLACEMENT_FAILED",
                safe_code="placement_unavailable",
                message="Localização indisponível.",
                actor_id="customer-user",
                contract_id="contract-1",
                correlation_id="corr-1",
            )
        self.assertEqual(incident["customer_id"], "42")
        event = _Events.published[-1]
        self.assertEqual(event["event_type"], "CUSTOMER_PLACEMENT_FAILED")
        self.assertEqual(event["correlation_id"], "corr-1")
        self.assertEqual(event["data"]["customer_id"], "42")
        self.assertNotIn("dedupe_key", event["data"])

    def test_dashboard_composition_installs_customer_health_without_baseline_change(self):
        server = (ROOT / "dashboard" / "server_part17.py").read_text(encoding="utf-8")
        self.assertIn("install_customer_health_http", server)
        placement = (ROOT / "dashboard" / "customer_placement_locations_http.py").read_text(encoding="utf-8")
        self.assertIn("CUSTOMER_PLACEMENT_FAILED", placement)
        baseline = (ROOT / "database" / "schema_baseline.py").read_text(encoding="utf-8")
        self.assertNotIn("customer_health_schema", baseline)


if __name__ == "__main__":
    unittest.main()
