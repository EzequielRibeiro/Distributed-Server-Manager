#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"

sys.path.insert(0, str(DATABASE))
sys.path.insert(0, str(DASHBOARD))


from agent_location_api import set_agent_location_for_user
from backend import DatabaseConfig
from backend_factory import create_backend
from location_repository import LocationRepository
from registry_repository import RegistryRepository


class AgentLocationApiTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(
                    Path(self.temp.name)
                    / "capivara.db"
                ),
            )
        )

        self.registry = RegistryRepository(
            self.backend
        )
        self.registry.create_aurora(
            password_hash="hash",
            manifest_path="manifest",
            metadata_json="{}",
        )

        self.locations = LocationRepository(
            self.backend
        )
        self.locations.initialize()

        self.locations.upsert_region(
            region_id="br-se",
            name="Brasil Sudeste",
            country_code="BR",
            continent_code="SA",
        )

        self.locations.upsert_datacenter(
            datacenter_id="dc-limeira",
            region_id="br-se",
            name="Limeira DC",
            provider="test",
            city="Limeira",
            country_code="BR",
        )

        self.admin = {
            "role": "admin",
            "scope_id": None,
        }

        self.controller = {
            "role": "controller",
            "scope_id": "controller-demo",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_admin_can_assign_agent_location(self):
        result = set_agent_location_for_user(
            self.admin,
            self.backend,
            {
                "agent_id": "agent-demo",
                "datacenter_id": "dc-limeira",
                "latitude": -22.56,
                "longitude": -47.40,
                "public_host": "agent.example.test",
            },
        )

        self.assertEqual(
            result["agent_id"],
            "agent-demo",
        )
        self.assertEqual(
            result["controller_id"],
            "controller-demo",
        )
        self.assertEqual(
            result["datacenter_id"],
            "dc-limeira",
        )
        self.assertEqual(
            result["region_id"],
            "br-se",
        )
        self.assertEqual(
            result["status"],
            "active",
        )

    def test_controller_can_assign_own_agent(self):
        result = set_agent_location_for_user(
            self.controller,
            self.backend,
            {
                "agent_id": "agent-demo",
                "datacenter_id": "dc-limeira",
            },
        )

        self.assertEqual(
            result["agent_id"],
            "agent-demo",
        )
        self.assertEqual(
            result["datacenter_id"],
            "dc-limeira",
        )

    def test_controller_outside_scope_is_rejected(self):
        user = {
            "role": "controller",
            "scope_id": "another-controller",
        }

        with self.assertRaisesRegex(
            PermissionError,
            "agent is outside user scope",
        ):
            set_agent_location_for_user(
                user,
                self.backend,
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-limeira",
                },
            )

    def test_customer_cannot_administer_agent(self):
        user = {
            "role": "customer",
            "scope_id": "CLI-DEMO-001",
        }

        with self.assertRaisesRegex(
            PermissionError,
            "agent administration is not permitted",
        ):
            set_agent_location_for_user(
                user,
                self.backend,
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-limeira",
                },
            )

    def test_missing_agent_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "agent not found",
        ):
            set_agent_location_for_user(
                self.admin,
                self.backend,
                {
                    "agent_id": "agent-inexistente",
                    "datacenter_id": "dc-limeira",
                },
            )

    def test_missing_datacenter_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "datacenter not found",
        ):
            set_agent_location_for_user(
                self.admin,
                self.backend,
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-inexistente",
                },
            )

    def test_invalid_latitude_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "latitude must be between -90 and 90",
        ):
            set_agent_location_for_user(
                self.admin,
                self.backend,
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-limeira",
                    "latitude": 91,
                },
            )

    def test_invalid_longitude_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "longitude must be between -180 and 180",
        ):
            set_agent_location_for_user(
                self.admin,
                self.backend,
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-limeira",
                    "longitude": 181,
                },
            )

    def test_invalid_coordinate_type_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "latitude must be a number",
        ):
            set_agent_location_for_user(
                self.admin,
                self.backend,
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-limeira",
                    "latitude": "invalid",
                },
            )

    def test_invalid_status_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "invalid location status",
        ):
            set_agent_location_for_user(
                self.admin,
                self.backend,
                {
                    "agent_id": "agent-demo",
                    "datacenter_id": "dc-limeira",
                    "status": "unknown",
                },
            )

    def test_payload_must_be_object(self):
        with self.assertRaisesRegex(
            ValueError,
            "payload must be an object",
        ):
            set_agent_location_for_user(
                self.admin,
                self.backend,
                None,
            )


if __name__ == "__main__":
    unittest.main()
