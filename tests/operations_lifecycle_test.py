#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from dashboard_repository import DashboardRepository
from registry_repository import RegistryRepository
from user_repository import UserRepository


class OperationsLifecycleTest(unittest.TestCase):
    def test_bootstrap_provision_audit_backup_restore_and_delete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "capivara.db"
            backup = root / "backups" / "capivara.db"
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
            users = UserRepository(backend)
            users.save(
                username="admin", password_hash="test-hash", role="admin",
            )
            dashboard = DashboardRepository(backend)
            with dashboard.session(transaction=True) as session:
                session.execute(
                    "INSERT INTO customers(id,controller_id,name,status) "
                    "VALUES (?,?,?,'active')",
                    ("customer-001", "controller-main", "Cliente Teste"),
                )
                session.execute(
                    "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit) "
                    "VALUES (?,?,?,'active',1)",
                    ("contract-001", "customer-001", "dayz"),
                )
            plan = dashboard.create_customer_instance(
                customer_id="customer-001",
                username="admin",
                game="dayz",
                runtime_id="dayz.stable",
                edition="stable",
                variant=None,
                version="latest",
                build="default",
                instances_root=root / "instances",
            )
            plan["metadata_path"].parent.mkdir(parents=True)
            plan["metadata_path"].write_text(
                '{"schema_version":2}\n', encoding="utf-8",
            )
            dashboard.update_instance_status(plan["instance_id"], "offline")
            dashboard.write_audit(
                "admin", plan["instance_id"],
                "instance.provision", "success", "acceptance test",
            )
            backup.parent.mkdir(parents=True)
            result = backend.backup(str(backup))
            self.assertTrue(backup.is_file())
            self.assertTrue(result)
            restored = create_backend(DatabaseConfig(
                driver="sqlite", database=str(backup),
            ))
            restored_dashboard = DashboardRepository(restored)
            self.assertIn(
                ("agent-node", "dayz", plan["instance_id"]),
                restored_dashboard.registered_instances(),
            )
            self.assertEqual(
                dashboard.delete_instance(plan["instance_id"]), 1,
            )
            restored.close()
            backend.close()


if __name__ == "__main__":
    unittest.main()
