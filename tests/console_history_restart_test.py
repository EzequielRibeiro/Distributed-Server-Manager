#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

from database.backend import DatabaseConfig
from database.backend_factory import create_backend
from database.dashboard_repository import DashboardRepository
from database.instance_workspace_repository import InstanceWorkspaceRepository
from database.registry_repository import RegistryRepository
from database.user_repository import UserRepository


class ConsoleHistoryRestartTest(unittest.TestCase):
    def test_repository_clears_only_target_instance_console_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            database = root / "capivara.db"
            backend = create_backend(DatabaseConfig(driver="sqlite", database=str(database)))
            registry = RegistryRepository(backend)
            registry.bootstrap_topology(
                controller_id="controller-main",
                controller_node_id="controller-node",
                controller_name="Controller",
                agent_id="agent-main",
                agent_node_id="agent-node",
                agent_name="Agent",
            )
            UserRepository(backend).save(
                username="admin",
                password_hash="test-hash",
                role="admin",
            )
            dashboard = DashboardRepository(backend)
            with dashboard.session(transaction=True) as session:
                session.execute(
                    "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,'active')",
                    ("customer-001", "controller-main", "Cliente"),
                )
                session.execute(
                    "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit) VALUES (?,?,?,'active',2)",
                    ("contract-001", "customer-001", "minecraft"),
                )

            first = dashboard.create_customer_instance(
                customer_id="customer-001",
                username="admin",
                game="minecraft",
                runtime_id="minecraft.java.youer",
                edition="java",
                variant=None,
                version="1.21.1",
                build="default",
                instances_root=root / "instances",
            )
            second = dashboard.create_customer_instance(
                customer_id="customer-001",
                username="admin",
                game="minecraft",
                runtime_id="minecraft.java.youer",
                edition="java",
                variant=None,
                version="1.21.1",
                build="default",
                instances_root=root / "instances",
            )

            repo = InstanceWorkspaceRepository(backend)
            with repo.session(transaction=True) as session:
                session.execute(
                    "INSERT INTO instance_console_output(instance_id,stream,line) VALUES (?,?,?)",
                    (first["instance_id"], "console", "first"),
                )
                session.execute(
                    "INSERT INTO instance_console_output(instance_id,stream,line) VALUES (?,?,?)",
                    (second["instance_id"], "console", "second"),
                )

            deleted = repo.clear_console_output(first["instance_id"])

            self.assertEqual(1, deleted)
            self.assertEqual([], repo.console_output(first["instance_id"], 100))
            self.assertEqual(
                ["second"],
                [row["line"] for row in repo.console_output(second["instance_id"], 100)],
            )
            backend.close()

    def test_restart_success_path_clears_console_history(self):
        source = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
        restart_guard = source.index('if action == "restart":')
        clear_call = source.index(".clear_console_output(instance_id)", restart_guard)
        audit_call = source.index("    audit(", clear_call)
        self.assertLess(restart_guard, clear_call)
        self.assertLess(clear_call, audit_call)


if __name__ == "__main__":
    unittest.main()
