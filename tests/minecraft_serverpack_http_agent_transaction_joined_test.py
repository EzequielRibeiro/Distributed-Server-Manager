"""Disposable HTTP -> Controller SQLite -> Agent transaction -> CAS joined test.

Uses real HTTP handler, Controller queue, Linux Agent transaction/journal/lock
and physical tempfile swap. The filesystem hooks simulate installer/readiness;
this test does not claim real JVM boot or physical multi-host transmission.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import urllib.request
from unittest.mock import patch

from tests.minecraft_serverpack_controller_flow_test import (
    ControllerServerPackFlowTest, Uploads, Workspace,
)
from tests.minecraft_serverpack_migration_http_enqueue_test import MigrationEnqueueHTTPTest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "agents/linux/runtime", ROOT / "core", ROOT / "dashboard"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import dashboard.minecraft_serverpack_migration_service as migration_service
import instance_runtime
from minecraft_serverpack_migration_transaction import execute_minecraft_serverpack_migration
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository


class JoinedCustomerAgentTransactionTest(ControllerServerPackFlowTest):
    def test_http_controller_to_agent_transaction_physical_swap_and_cas(self):
        service = migration_service.MinecraftServerPackMigrationService.__new__(
            migration_service.MinecraftServerPackMigrationService
        )
        service.backend = self.backend
        service.root = ROOT
        service.workspace = Workspace()
        service.uploads = Uploads(self.prepared)
        selection = {
            "runtime_definition": "minecraft.java.neoforge",
            "environment_id": "minecraft.java.neoforge",
            "game": "minecraft",
            "version": "26.1.2",
            "build": "26.1.2.109",
            "provider": "http",
            "installer": {"type": "java_jar"},
            "asset": {"sha256": "e" * 64, "url": "https://maven.neoforged.net/example.jar"},
        }
        policy = {
            "CAPIVARA_SERVERPACK_MIGRATION_MODE": "",
            "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION": "YES",
        }
        with patch.dict(os.environ, policy), patch.object(
            migration_service, "resolve_catalog_provisioning",
            return_value=(selection, {"catalog_runtime_id": "minecraft.java.neoforge"}),
        ):
            server, thread, patcher, _ = MigrationEnqueueHTTPTest()._server(
                lambda calls: lambda backend, root: service
            )
            try:
                body = {
                    "instance_id": "pr855-controller-e2e",
                    "transfer_id": "transfer-e2e",
                    "content_id": "atm11",
                    "content_type": "modpack",
                    "metadata": {"serverpack": {"format": "official-serverpack-v1"}},
                    "migration_plan_sha256": "c" * 64,
                }
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}"
                    "/api/customer/instance/workspace/content/upload/migration/enqueue",
                    method="POST", data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    self.assertEqual(response.status, 202)
                    accepted = json.load(response)["migration"]
            finally:
                patcher.stop()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            jobs = AgentInstanceProvisioningRepository(self.backend)
            provisioning_id = accepted["provisioning_id"]
            queued = jobs.snapshot(provisioning_id)
            request = queued["request"]
            migration = request["configuration"]["minecraft_serverpack_migration"]
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(
                self.content.bundle_history("pr855-controller-e2e", "atm11")[0]["revision"], 1
            )
            root = Path(self.temp.name) / "agent-lab"
            root.mkdir()
            state = root / "agent-state"
            old = root / "storage" / "runtime"
            stage = root / "storage" / "runtime.migration-stage"
            rollback = root / "storage" / "runtime.migration-rollback"
            old.mkdir(parents=True)
            stage.mkdir(parents=True)
            (old / "world").mkdir()
            (old / "world" / "original-marker.txt").write_text("PRESERVED")
            (old / "loader.txt").write_text("26.1.2.94")
            (stage / "world").mkdir()
            (stage / "world" / "original-marker.txt").write_text("PRESERVED")
            (stage / "loader.txt").write_text("26.1.2.109")
            backup = root / "retained-backup.tar.gz"
            with tarfile.open(backup, "w:gz") as archive:
                archive.add(old / "world" / "original-marker.txt", arcname="world/original-marker.txt")
            digest = hashlib.sha256(backup.read_bytes()).hexdigest()
            proof = {
                "backup_id": "isolated-verified-backup",
                "sha256": digest,
                "size_bytes": backup.stat().st_size,
                "integrity_verified": True,
            }
            def revalidate(evidence):
                return {"valid": True, "install_allowed": False,
                        "migration_plan_sha256": evidence["migration_plan_sha256"]}
            def capacity(evidence):
                return {"sufficient": True, "install_allowed": False,
                        "requires_exclusive_recheck": True}
            def stop(*_):
                self.assertTrue(old.exists())
            def verify_backup(*_):
                self.assertEqual(hashlib.sha256(backup.read_bytes()).hexdigest(), digest)
                return proof
            def stage_files(*_):
                self.assertTrue((stage / "loader.txt").is_file())
            def swap(*_):
                os.rename(old, rollback)
                os.rename(stage, old)
            def ready(*_):
                return (old / "loader.txt").read_text() == "26.1.2.109" and (
                    old / "world/original-marker.txt"
                ).read_text() == "PRESERVED"
            journal = {
                "phase": "committed",
                "migration_plan_sha256": migration["migration_plan_sha256"],
                "target_loader_version": migration["target_loader_version"],
            }
            def commit(*_):
                location = root / "history" / "minecraft-serverpack-migration.json"
                location.parent.mkdir()
                location.write_text(json.dumps(journal) + "\n")
                return {"status": "committed", "journal": json.loads(location.read_text())}
            def finalize(*_):
                self.assertTrue(rollback.is_dir())
                return {"status": "archived", "observed_state": "stopped"}
            hooks = {
                "revalidate": revalidate, "capacity": capacity, "backup": verify_backup,
                "stop": stop, "stage": stage_files, "swap": swap, "readiness": ready,
                "commit": commit, "finalize": finalize,
                "rollback": lambda *_: self.fail("rollback unexpectedly called"),
            }
            with patch.object(instance_runtime, "STATE_DIR", state):
                detail = execute_minecraft_serverpack_migration(
                    {"agent_id": "pr839-isolated-agent"},
                    "pr855-controller-e2e", migration, hooks,
                )
            self.assertEqual(detail["status"], "completed")
            self.assertEqual(detail["commit"]["journal"]["phase"], "committed")
            self.assertEqual((old / "world/original-marker.txt").read_text(), "PRESERVED")
            self.assertEqual((rollback / "loader.txt").read_text(), "26.1.2.94")
            result = {
                "provisioning_id": provisioning_id,
                "instance_id": "pr855-controller-e2e",
                "status": detail["status"], "progress": 100, "current_step": "completed",
                "minecraft_serverpack_migration": detail,
            }
            mismatch = json.loads(json.dumps(result))
            mismatch["minecraft_serverpack_migration"]["commit"]["journal"]["migration_plan_sha256"] = "f" * 64
            with self.assertRaises(Exception):
                jobs.apply_result("pr839-isolated-agent", mismatch)
            self.assertEqual(jobs.snapshot(provisioning_id)["status"], "queued")
            self.assertEqual(self.content.bundle_history("pr855-controller-e2e", "atm11")[0]["revision"], 1)
            final = jobs.apply_result("pr839-isolated-agent", result)
            self.assertEqual(final["status"], "completed")
            self.assertEqual(self.content.bundle_history("pr855-controller-e2e", "atm11")[0]["revision"], 2)
            replay = jobs.apply_result("pr839-isolated-agent", result)
            self.assertEqual(replay["status"], "completed")
            self.assertEqual(self.content.bundle_history("pr855-controller-e2e", "atm11")[0]["revision"], 2)
            print("PASS_JOINED_AGENT_TRANSACTION_HTTP_CONTROLLER_CAS", json.dumps({
                "http": 202, "revision": 2, "agent_core_status": detail["status"],
                "journal": detail["commit"]["journal"]["phase"],
                "physical_swap": True, "rollback_copy": True, "original_world": True,
                "stale_fingerprint_rejected": True, "replay_idempotent": True,
                "real_jvm_boot": False, "physical_multi_host": False,
            }, sort_keys=True), flush=True)
