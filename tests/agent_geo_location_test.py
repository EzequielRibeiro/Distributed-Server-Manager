#!/usr/bin/env python3
"""Agent-owned GeoIP and controller/Agent location separation."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "database", ROOT / "agents/linux/runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from registry_repository import RegistryRepository
from location_repository import LocationRepository
from agent_geolocation import sync_agent_reported_location, controller_location_for_agent
from agent_location_api import set_agent_location_for_user
from host_geolocation import observe_host_geolocation, _CACHE


def sample_geo(ip="187.127.254.105", country="US", state="MA"):
    return {
        "public_ipv4_observation": {"status": "observed", "public_ipv4": ip},
        "geo_location_observation": {
            "status": "observed", "kind": "geoip_estimated", "source": "ipwho.is",
            "public_ipv4": ip, "country_code": country,
            "country_name": "United States", "state_code": state,
            "state_name": "Massachusetts", "city": "Boston",
            "latitude": 42.35843, "longitude": -71.05977,
        },
    }


class AgentGeolocationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"),
        ))
        self.backend.initialize()
        RegistryRepository(self.backend).bootstrap_topology(
            controller_id="controller-main",
            controller_node_id="controller-node",
            controller_name="Controller BR",
            agent_id="agent-remote",
            agent_node_id="agent-node",
            agent_name="VPS",
        )
        self.geo = LocationRepository(self.backend)
        self.geo.upsert_region(region_id="br-sp", name="Sao Paulo", country_code="BR")
        self.geo.upsert_datacenter(datacenter_id="dc-br", region_id="br-sp",
                                    name="Brazil", country_code="BR", state_code="SP")
        self.geo.upsert_agent_location(agent_id="agent-remote", datacenter_id="dc-br")
        _CACHE.update(ip=None, expires=0, result=None)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _location(self):
        with self.geo.session() as session:
            return session.execute(
                "SELECT al.datacenter_id,d.country_code,d.state_code "
                "FROM agent_locations al JOIN datacenters d ON d.id=al.datacenter_id "
                "WHERE al.agent_id=?", ("agent-remote",),
            ).fetchone()

    def test_authenticated_agent_geo_replaces_wrong_install_region(self):
        self.assertTrue(sync_agent_reported_location("agent-remote", sample_geo(), backend=self.backend))
        row = self._location()
        self.assertEqual(row["country_code"], "US")
        self.assertEqual(row["state_code"], "MA")
        self.assertEqual(row["datacenter_id"], "geo-agent-remote")
        self.assertFalse(sync_agent_reported_location("agent-remote", sample_geo(), backend=self.backend))

    def test_forged_ip_mismatch_never_updates_location(self):
        data = sample_geo()
        data["geo_location_observation"]["public_ipv4"] = "1.1.1.1"
        self.assertFalse(sync_agent_reported_location("agent-remote", data, backend=self.backend))
        self.assertEqual(self._location()["datacenter_id"], "dc-br")

    def test_private_or_malformed_geoip_does_not_change_placement(self):
        self.assertFalse(sync_agent_reported_location("agent-remote", sample_geo(ip="192.168.1.2"), backend=self.backend))
        self.assertFalse(sync_agent_reported_location("agent-remote", sample_geo(country="USA"), backend=self.backend))
        self.assertEqual(self._location()["datacenter_id"], "dc-br")

    def test_admin_override_remains_authoritative(self):
        set_agent_location_for_user(
            {"role": "admin"}, self.backend,
            {"agent_id": "agent-remote", "datacenter_id": "dc-br"},
        )
        self.assertFalse(sync_agent_reported_location("agent-remote", sample_geo(), backend=self.backend))
        self.assertEqual(self._location()["datacenter_id"], "dc-br")

    def test_controller_location_is_not_inherited_by_agent(self):
        info = controller_location_for_agent("agent-remote", backend=self.backend)
        self.assertEqual(info["controller_id"], "controller-main")
        self.assertIsNone(info["country_code"])

    def test_agent_observation_is_cached(self):
        geo = sample_geo()["geo_location_observation"]
        with patch("host_geolocation._lookup", return_value=geo) as lookup:
            first = observe_host_geolocation({"status": "observed", "public_ipv4": "187.127.254.105"})
            second = observe_host_geolocation({"status": "observed", "public_ipv4": "187.127.254.105"})
        self.assertEqual(first["country_code"], "US")
        self.assertEqual(second["country_code"], "US")
        lookup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
