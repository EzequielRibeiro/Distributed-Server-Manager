
#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"

sys.path.insert(
    0,
    str(DATABASE),
)


from agent_port_repository import (
    AgentPortRepository,
)
from backend import DatabaseConfig
from backend_factory import create_backend
from registry_repository import (
    RegistryRepository,
)


class AgentPortRepositoryTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp = (
            tempfile.TemporaryDirectory()
        )

        backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(
                    Path(
                        self.temp.name
                    )
                    / "capivara.db"
                ),
            )
        )

        self.repository = (
            AgentPortRepository(
                backend
            )
        )

        self.repository.initialize()

        RegistryRepository(
            backend
        ).bootstrap_installation_profile(
            profile="hybrid",
            node_id="node-demo",
            node_name="Demo Node",
            controller_id="controller-demo",
            controller_name="Demo Controller",
            agent_id="agent-demo",
            agent_name="Demo Agent",
            region_id="region-demo",
            region_name="Demo Region",
            datacenter_id="dc-demo",
            datacenter_name="Demo Datacenter",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_default_ranges(self):
        summary = (
            self.repository.summary(
                "agent-demo"
            )
        )

        ranges = {
            (
                item["protocol"],
                int(
                    item["start_port"]
                ),
                int(
                    item["end_port"]
                ),
            )
            for item
            in summary["ranges"]
        }

        self.assertEqual(
            ranges,
            {
                (
                    "tcp",
                    24000,
                    24999,
                ),
                (
                    "udp",
                    24000,
                    24999,
                ),
            },
        )

    def test_agent_listing_excludes_decommissioned_by_default(self):
        backend = self.repository.backend

        with backend.transaction() as connection:
            connection.execute(
                "UPDATE agents SET status=? WHERE id=?",
                ("decommissioned", "agent-demo"),
            )

        agents = self.repository.list_agents()

        self.assertNotIn(
            "agent-demo",
            {str(item["id"]) for item in agents},
        )

    def test_agent_listing_can_show_decommissioned(self):
        backend = self.repository.backend

        with backend.transaction() as connection:
            connection.execute(
                "UPDATE agents SET status=? WHERE id=?",
                ("decommissioned", "agent-demo"),
            )

        agents = self.repository.list_agents(
            lifecycle="decommissioned",
        )

        self.assertEqual(
            {str(item["id"]) for item in agents},
            {"agent-demo"},
        )
        self.assertEqual(
            str(agents[0]["status"]),
            "decommissioned",
        )

    def test_agent_listing_all_includes_decommissioned(self):
        backend = self.repository.backend

        with backend.transaction() as connection:
            connection.execute(
                "UPDATE agents SET status=? WHERE id=?",
                ("decommissioned", "agent-demo"),
            )

        agents = self.repository.list_agents(
            lifecycle="all",
        )

        self.assertIn(
            "agent-demo",
            {str(item["id"]) for item in agents},
        )

    def test_agent_listing_rejects_unknown_lifecycle(self):
        with self.assertRaisesRegex(
            ValueError,
            "lifecycle must be",
        ):
            self.repository.list_agents(
                lifecycle="unknown",
            )

    def test_change_range(self):
        self.repository.set_ranges(
            "agent-demo",
            protocols=(
                "tcp",
                "udp",
            ),
            start_port=30000,
            end_port=30999,
        )

        summary = (
            self.repository.summary(
                "agent-demo"
            )
        )

        self.assertTrue(
            all(
                int(
                    item["start_port"]
                )
                == 30000
                for item
                in summary["ranges"]
            )
        )


if __name__ == "__main__":
    unittest.main()
