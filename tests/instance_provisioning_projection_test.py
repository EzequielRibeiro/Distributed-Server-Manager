#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from instance_provisioning_projection import dashboard_provision_state, project_agent_provisioning
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class ProvisioningProjectionTest(unittest.TestCase):
    def test_failed_steam_auth_keeps_retryable_customer_state(self):
        projected = dashboard_provision_state(
            {
                "provisioning_id": "p1",
                "instance_id": "i1",
                "status": "failed",
                "current_step": "install_content",
                "progress": 100,
                "last_error": "Steam Guard authentication required",
            }
        )
        self.assertEqual(projected["status"], "pending_steam_auth")
        self.assertEqual(projected["stage"], "steam_auth")
        self.assertEqual(projected["progress"], 35)
        self.assertTrue(projected["distributed"])

    def test_agent_progress_and_completion_update_legacy_read_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend = create_backend(DatabaseConfig(driver="sqlite", database=str(root / "capivara.db")))
            backend.initialize()
            identity = installation_profile_identity(
                RegistryRepository(backend), profile="hybrid", hostname="projection-host"
            )
            controller_id = str(identity["controller_id"])
            agent_id = str(identity["agent_id"])
            node_id = str(identity["node_id"])
            with backend.transaction() as connection:
                connection.execute(
                    "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                    ("customer-projection", controller_id, "Projection Customer", "active"),
                )
                connection.execute(
                    "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        "instance-projection",
                        node_id,
                        "dayz",
                        "dayz.stable",
                        "Projection",
                        "queued",
                        controller_id,
                        agent_id,
                        "customer-projection",
                    ),
                )
            resource = root / "runtime" / "resources" / node_id / "dayz" / "instance-projection"
            resource.mkdir(parents=True)

            running = project_agent_provisioning(
                backend,
                {
                    "provisioning_id": "p-running",
                    "instance_id": "instance-projection",
                    "status": "running",
                    "current_step": "materialize_runtime",
                    "progress": 82,
                },
                root=root,
            )
            self.assertEqual(running["status"], "provisioning")
            self.assertEqual(running["progress"], 82)

            completed = project_agent_provisioning(
                backend,
                {
                    "provisioning_id": "p-running",
                    "instance_id": "instance-projection",
                    "status": "completed",
                    "current_step": "completed",
                    "progress": 100,
                    "result": {"observed_state": "stopped"},
                },
                root=root,
            )
            self.assertEqual(completed["status"], "offline")
            with backend.connect() as connection:
                row = connection.execute(
                    "SELECT status FROM instances WHERE id=?", ("instance-projection",)
                ).fetchone()
            self.assertEqual(row["status"], "offline")
            self.assertIn('"distributed": true', (resource / "provision.json").read_text(encoding="utf-8"))
            backend.close()


if __name__ == "__main__":
    unittest.main()
