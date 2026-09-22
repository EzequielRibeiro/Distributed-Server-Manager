#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_update_repository import AgentUpdateRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from hybrid_local_reconciliation import reconcile_local_hybrid_runtime
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class HybridAgentUpdateReconciliationTest(unittest.TestCase):
    def test_hybrid_runtime_reports_controller_version_and_closes_stale_rollout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("config").mkdir(parents=True)
            root.joinpath("config", "agent.conf").write_text(
                'DSM_NODE_ROLE="hybrid"\n', encoding="utf-8"
            )
            backend = create_backend(
                DatabaseConfig(driver="sqlite", database=str(root / "capivara.db"))
            )
            try:
                registry = RegistryRepository(backend)
                identity = installation_profile_identity(
                    registry, profile="hybrid", hostname="hybrid-update"
                )
                agent_id = str(identity["agent_id"])
                updates = AgentUpdateRepository(backend)
                updates.initialize()
                updates.create_rollout(
                    [agent_id], desired_version="2.0.53", channel="stable", batch_size=1
                )

                inventory = {
                    "hostname": "hybrid-update",
                    "os_name": "linux",
                    "architecture": "x86_64",
                    "capivara_version": "2.0.53",
                    "capabilities": {},
                    "cpu": {},
                    "ram_total_bytes": 1024,
                    "storage": {},
                    "network": {},
                }
                with patch(
                    "hybrid_local_reconciliation.reconcile_hybrid_runtime_ports",
                    return_value={"status": "completed"},
                ):
                    result = reconcile_local_hybrid_runtime(
                        registry,
                        root,
                        node_id="hybrid-update",
                        agent_id=agent_id,
                        hostname="hybrid-update",
                        inventory=inventory,
                    )

                state = updates.snapshot(agent_id)
                self.assertEqual(state["installed_version"], "2.0.53")
                self.assertEqual(state["update_status"], "completed")
                self.assertIsNotNone(state["last_update"])
                self.assertEqual(result["update_state"]["update_status"], "completed")
            finally:
                backend.close()


    def test_hybrid_runtime_closes_rollout_when_controller_is_newer_than_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("config").mkdir(parents=True)
            root.joinpath("config", "agent.conf").write_text(
                'DSM_NODE_ROLE="hybrid"\n', encoding="utf-8"
            )
            backend = create_backend(
                DatabaseConfig(driver="sqlite", database=str(root / "capivara.db"))
            )
            try:
                registry = RegistryRepository(backend)
                identity = installation_profile_identity(
                    registry, profile="hybrid", hostname="hybrid-update-newer"
                )
                agent_id = str(identity["agent_id"])
                updates = AgentUpdateRepository(backend)
                updates.initialize()
                updates.create_rollout(
                    [agent_id], desired_version="2.0.53", channel="stable", batch_size=1
                )

                inventory = {
                    "hostname": "hybrid-update-newer",
                    "os_name": "linux",
                    "architecture": "x86_64",
                    "capivara_version": "2.0.114",
                    "capabilities": {},
                    "cpu": {},
                    "ram_total_bytes": 1024,
                    "storage": {},
                    "network": {},
                }
                with patch(
                    "hybrid_local_reconciliation.reconcile_hybrid_runtime_ports",
                    return_value={"status": "completed"},
                ):
                    result = reconcile_local_hybrid_runtime(
                        registry,
                        root,
                        node_id="hybrid-update-newer",
                        agent_id=agent_id,
                        hostname="hybrid-update-newer",
                        inventory=inventory,
                    )

                state = updates.snapshot(agent_id)
                self.assertEqual(state["installed_version"], "2.0.114")
                self.assertEqual(state["available_version"], "2.0.114")
                self.assertEqual(state["desired_version"], "2.0.114")
                self.assertEqual(state["update_status"], "completed")
                self.assertIsNotNone(state["last_update"])
                self.assertEqual(result["update_state"]["update_status"], "completed")
            finally:
                backend.close()


if __name__ == "__main__":
    unittest.main()
