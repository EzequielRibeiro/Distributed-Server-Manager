#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from operations import operational_readiness
from registry_repository import RegistryRepository
from user_repository import UserRepository


class OperationsReadinessTest(unittest.TestCase):
    def test_readiness_requires_topology_admin_and_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            old = os.environ.copy()
            os.environ.update({
                "DSM_DATABASE_DRIVER": "sqlite",
                "DSM_DATABASE": str(database),
            })
            try:
                backend = create_backend(DatabaseConfig(
                    driver="sqlite", database=str(database),
                ))
                registry = RegistryRepository(backend)
                registry.bootstrap_topology(
                    controller_id="controller-main",
                    controller_node_id="controller-node",
                    controller_name="Controlador Principal",
                    agent_id="agent-main",
                    agent_node_id="agent-node",
                    agent_name="Agente Principal",
                )
                UserRepository(backend).save(
                    username="admin", password_hash="hash", role="admin",
                )
                backend.close()
                for name in ("config", "data", "logs", "runtime"):
                    (root / name).mkdir(exist_ok=True)
                payload = operational_readiness(root)
                self.assertTrue(payload["ready"])
                self.assertEqual(payload["database_backend"], "sqlite")
                self.assertNotIn("password", str(payload).lower())
                (root / "logs").rmdir()
                self.assertFalse(operational_readiness(root)["ready"])
            finally:
                os.environ.clear()
                os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
