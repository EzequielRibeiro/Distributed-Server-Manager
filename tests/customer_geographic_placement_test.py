#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from core.placement_requirements import PlacementRequirements
from customer_placement_locations import customer_placement_locations
from customer_placement_locations_http import dispatch_customer_placement_locations_get
from placement_errors import PlacementUnavailable


class _Row(dict):
    pass


class _Session:
    def __init__(self):
        self.sql = ""

    def execute(self, sql, _params):
        self.sql = sql
        return self

    def fetchone(self):
        if "service_contracts" in self.sql:
            return _Row(id="contract-1", customer_id=42, status="active", metadata_json=json.dumps({"resources": {"cpu_cores": 4, "memory_bytes": 8589934592, "storage_bytes": 53687091200}}))
        return _Row(id=42, controller_id="controller-a", status="active")


class _Repository:
    dialect = type("Dialect", (), {"placeholder": "?"})()

    def __init__(self, _backend):
        pass

    def initialize(self):
        return None

    @contextmanager
    def session(self):
        yield _Session()

    def regions(self):
        return [
            {"id": "br-sudeste", "name": "São Paulo", "country_code": "BR", "latitude": -23.55, "longitude": -46.63},
            {"id": "us-east", "name": "Miami", "country_code": "US", "latitude": 25.76, "longitude": -80.19},
        ]

    def candidates(self, _controller_id, region_id=None):
        rows = [
            {"agent_id": "secret-agent-sp", "node_id": "secret-node-sp", "region_id": "br-sudeste", "public_host": "10.0.0.10", "fingerprint": "secret-fingerprint"},
            {"agent_id": "secret-agent-us", "node_id": "secret-node-us", "region_id": "us-east", "public_host": "10.0.0.20", "fingerprint": "other-secret"},
        ]
        return [row for row in rows if region_id is None or row["region_id"] == region_id]


def _decision(*_args, **kwargs):
    region = kwargs.get("preferred_region_id")
    if region == "us-east":
        return {"score": 10.0, "agent_id": "secret-agent-us", "node_id": "secret-node-us", "region_id": region, "datacenter_id": "secret-dc-us"}
    return {"score": 90.0, "agent_id": "secret-agent-sp", "node_id": "secret-node-sp", "region_id": region, "datacenter_id": "secret-dc-sp"}


class CustomerGeographicPlacementTest(unittest.TestCase):
    def test_customer_receives_only_public_logical_locations(self):
        with patch("customer_placement_locations.LocationRepository", _Repository), patch("customer_placement_locations.requirements_for_instance", return_value=PlacementRequirements()) as requirements, patch("customer_placement_locations.choose_agent_for_instance", side_effect=_decision):
            payload = customer_placement_locations({"role": "customer", "scope_id": "CLI-000042"}, object(), game_id="dayz", runtime_id="dayz.stable", contract_id="contract-1", client_latitude=-23.55, client_longitude=-46.63)
        self.assertEqual(payload["selection_scope"], "region")
        self.assertEqual(len(payload["locations"]), 2)
        self.assertTrue(payload["locations"][0]["recommended"])
        self.assertEqual(payload["locations"][0]["region_id"], "br-sudeste")
        self.assertEqual(payload["locations"][0]["latency"]["kind"], "estimated")
        self.assertIsInstance(payload["locations"][0]["latency"]["value_ms"], int)
        self.assertEqual(requirements.call_args.kwargs["resources"]["cpu_cores"], 4)
        serialized = json.dumps(payload)
        for secret in ("secret-agent-sp", "secret-agent-us", "secret-node-sp", "secret-node-us", "10.0.0.10", "10.0.0.20", "secret-fingerprint", "secret-dc-sp", "secret-dc-us"):
            self.assertNotIn(secret, serialized)

    def test_unavailable_region_is_not_recommended(self):
        def choose(*args, **kwargs):
            if kwargs.get("preferred_region_id") == "us-east":
                raise PlacementUnavailable(reason="requested_region_unavailable", agents_evaluated=2, requested_region_id="us-east")
            return _decision(*args, **kwargs)
        with patch("customer_placement_locations.LocationRepository", _Repository), patch("customer_placement_locations.requirements_for_instance", return_value=PlacementRequirements()), patch("customer_placement_locations.choose_agent_for_instance", side_effect=choose):
            payload = customer_placement_locations({"role": "customer", "scope_id": "CLI-000042"}, object())
        by_region = {item["region_id"]: item for item in payload["locations"]}
        self.assertEqual(by_region["us-east"]["availability"], "unavailable")
        self.assertFalse(by_region["us-east"]["recommended"])

    def test_non_customer_is_denied(self):
        with patch("customer_placement_locations.LocationRepository", _Repository):
            with self.assertRaises(PermissionError):
                customer_placement_locations({"role": "admin", "scope_id": "CLI-000042"}, object())

    def test_http_rejects_invalid_coordinates_without_exposing_details(self):
        status, payload = dispatch_customer_placement_locations_get("/api/customer/placement/locations", user={"role": "customer", "scope_id": "CLI-000042"}, backend=object(), query={"latitude": ["not-a-number"]})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_request")

    def test_customer_page_loads_explicit_placement_client_before_runtime_selector(self):
        html = (ROOT / "dashboard" / "web" / "customer.html").read_text(encoding="utf-8")
        self.assertIn("/customer-placement-client.js", html)
        self.assertNotIn("/customer-placement-selector.js", html)
        self.assertLess(html.index("/customer-placement-client.js"), html.index("/runtime-selector.js"))

        client = (ROOT / "dashboard" / "web" / "customer-placement-client.js").read_text(encoding="utf-8")
        self.assertIn("/api/customer/placement/locations", client)
        self.assertIn("PLACEMENT_TIMEOUT_MS = 8000", client)
        self.assertIn("placement_timeout", client)
        self.assertIn("placement_no_available_agent", client)
        self.assertIn("Verificando servidores disponíveis", client)
        self.assertNotIn("window.fetch =", client)
        self.assertNotIn("agent_id", client)
        self.assertNotIn("public_host", client)
        self.assertNotIn("fingerprint", client)

        selector = (ROOT / "dashboard" / "web" / "runtime-selector.js").read_text(encoding="utf-8")
        self.assertIn("CapivaraPlacementClient", selector)
        self.assertIn("loadRegions", selector)
        self.assertNotIn("/api/customer/regions", selector)

    def test_customer_creation_response_does_not_publish_internal_placement(self):
        source = (ROOT / "dashboard" / "customer_instance_creation.py").read_text(encoding="utf-8")
        public_result = source[source.index('result={"created"'):source.index('if source_vault_id:result')]
        self.assertNotIn('"agent_id"', public_result)
        self.assertNotIn('"node_id"', public_result)
        self.assertNotIn('"datacenter_id"', public_result)
        self.assertNotIn('"instance":', public_result)
        self.assertIn('"correlation_id"', public_result)
        self.assertIn('"region_id"', public_result)


if __name__ == "__main__":
    unittest.main()
