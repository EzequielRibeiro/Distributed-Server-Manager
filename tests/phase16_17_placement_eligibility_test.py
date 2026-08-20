#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
AGENT_RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, DATABASE, DASHBOARD, AGENT_RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core.placement_requirements import requirements_for_instance
from agent_port_availability import effective_port_summary
from agent_port_repository import AgentPortRepository
from agent_runtime_repository import AgentRuntimeRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from network_inventory import collect_network_inventory
from placement_errors import PlacementUnavailable
from placement_service import choose_agent_for_instance
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class Phase1617PlacementEligibilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        self.identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="hybrid", hostname="phase16-agent"
        )
        self.agent_id = self.identity["agent_id"]
        self.controller_id = self.identity["controller_id"]

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _inventory(self, *, steamcmd=True, java=True, network=None, threads=8, ram=16 * 1024**3, storage=100 * 1024**3):
        repository = AgentRuntimeRepository(self.backend)
        repository.upsert_inventory(
            agent_id=self.agent_id,
            hostname="phase16-agent",
            os_name="linux",
            architecture="x86_64",
            capabilities={
                "native-linux": True,
                "steamcmd": steamcmd,
                "java": java,
                "backup": False,
                "mod-management": False,
            },
            cpu={"logical_cores": threads},
            ram_total_bytes=ram,
            storage={"root_free_bytes": storage},
            network=network or {"tcp_listen": [], "udp_listen": []},
        )
        repository.heartbeat(self.agent_id)

    def test_effective_summary_counts_real_socket_as_conflict_and_unavailable(self):
        self._inventory(network={"tcp_listen": [], "udp_listen": [24000]})
        summary = effective_port_summary(self.backend, self.agent_id)
        udp = next(item for item in summary["ranges"] if item["protocol"] == "udp")
        self.assertEqual(udp["capacity"], 1000)
        self.assertEqual(udp["reserved"], 0)
        self.assertEqual(udp["observed_occupied"], 1)
        self.assertEqual(udp["available"], 999)
        self.assertEqual(udp["largest_contiguous_available"], 999)
        self.assertEqual(summary["observed_conflict_count"], 1)

    def test_steam_native_runtime_requires_catalog_declared_infrastructure(self):
        requirements = requirements_for_instance(game_id="dayz", runtime_id="dayz.stable")
        self.assertEqual(requirements.capabilities, frozenset({"native-linux", "steamcmd"}))
        self.assertEqual(len(requirements.ports), 1)
        self.assertEqual(requirements.ports[0].protocol, "udp")
        self.assertEqual(requirements.ports[0].count, 10)
        self.assertTrue(requirements.ports[0].contiguous)

        self._inventory(steamcmd=True)
        decision = choose_agent_for_instance(self.backend, controller_id=self.controller_id, requirements=requirements)
        self.assertEqual(decision["agent_id"], self.agent_id)

        AgentPortRepository(self.backend).set_ranges(
            self.agent_id, protocols=("udp",), start_port=24000, end_port=24009
        )
        self._inventory(steamcmd=True, network={"tcp_listen": [], "udp_listen": [24000]})
        with self.assertRaises(PlacementUnavailable):
            choose_agent_for_instance(self.backend, controller_id=self.controller_id, requirements=requirements)

    def test_catalog_runtime_without_required_primitive_is_not_eligible(self):
        self._inventory(steamcmd=False)
        requirements = requirements_for_instance(game_id="dayz", runtime_id="dayz.stable")
        with self.assertRaises(PlacementUnavailable):
            choose_agent_for_instance(self.backend, controller_id=self.controller_id, requirements=requirements)

    def test_java_requirement_is_inferred_without_game_specific_capability(self):
        requirements = requirements_for_instance(
            game_id="minecraft", runtime_id="minecraft.java.vanilla"
        )
        self.assertIn("java", requirements.capabilities)
        self.assertNotIn("minecraft-java", requirements.capabilities)
        self._inventory(java=False)
        with self.assertRaises(PlacementUnavailable):
            choose_agent_for_instance(self.backend, controller_id=self.controller_id, requirements=requirements)

    def test_resource_capacity_is_enforced_when_requested(self):
        self._inventory(threads=4, ram=4 * 1024**3, storage=8 * 1024**3)
        requirements = requirements_for_instance(
            game_id=None,
            resources={
                "min_cpu_threads": 8,
                "min_ram_bytes": 8 * 1024**3,
                "min_storage_free_bytes": 20 * 1024**3,
            },
        )
        with self.assertRaises(PlacementUnavailable):
            choose_agent_for_instance(self.backend, controller_id=self.controller_id, requirements=requirements)

    def test_linux_network_inventory_parses_ss_local_endpoint(self):
        completed = type("Completed", (), {"stdout": "LISTEN 0 128 0.0.0.0:2456 0.0.0.0:*\n"})()
        with patch("network_inventory.subprocess.run", return_value=completed):
            inventory = collect_network_inventory()
        self.assertEqual(inventory["tcp_listen"], [2456])
        self.assertEqual(inventory["udp_listen"], [2456])


if __name__ == "__main__":
    unittest.main()
