#!/usr/bin/env python3
"""Controller -> Hybrid readiness regression through real placement boundaries."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from backend import DatabaseConfig
from backend_factory import create_backend
from core.placement_requirements import requirements_for_instance
from hybrid_local_reconciliation import reconcile_local_hybrid_runtime
from infrastructure_role_cli import promote_local_controller
from placement_service import choose_agent_for_instance
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class ControllerToHybridPlacementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dsm"
        (self.root / "config").mkdir(parents=True)
        (self.root / "config" / "agent.conf").write_text(
            'AGENT_ID=""\nAGENT_NAME=""\nAGENT_STATUS="pending"\nDSM_NODE_ID=""\n',
            encoding="utf-8",
        )
        (self.root / "version").write_text("1.4.3\n", encoding="utf-8")
        steamcmd = self.root / "tools" / "steamcmd" / "steamcmd.sh"
        steamcmd.parent.mkdir(parents=True)
        steamcmd.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.repository = RegistryRepository(self.backend)
        self.identity = installation_profile_identity(
            self.repository,
            profile="controller",
            hostname="hybrid-placement-host",
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_promoted_local_hybrid_becomes_dayz_placement_eligible(self):
        transition = promote_local_controller(
            self.repository,
            node_id="hybrid-placement-host",
        )
        agent_id = str(transition["agent_id"])

        with patch(
            "hybrid_local_reconciliation.collect_network_inventory",
            return_value={"source": "test", "tcp_listen": [], "udp_listen": []},
        ):
            runtime = reconcile_local_hybrid_runtime(
                self.repository,
                self.root,
                node_id="hybrid-placement-host",
                agent_id=agent_id,
                hostname="hybrid-placement-host",
            )

        self.assertEqual(runtime["health_status"], "online")
        self.assertTrue(runtime["capabilities"].get("native-linux"))
        self.assertTrue(runtime["capabilities"].get("steamcmd"))
        self.assertTrue(
            any(
                row["protocol"] == "udp"
                and int(row["start_port"]) == 24000
                and int(row["end_port"]) == 24999
                for row in runtime["port_ranges"]
            )
        )

        requirements = requirements_for_instance(game_id="dayz", runtime_id="dayz.stable")
        decision = choose_agent_for_instance(
            self.backend,
            controller_id=str(self.identity["controller_id"]),
            requirements=requirements,
        )
        self.assertEqual(decision["agent_id"], agent_id)
        self.assertEqual(decision["node_id"], "hybrid-placement-host")


if __name__ == "__main__":
    unittest.main()
