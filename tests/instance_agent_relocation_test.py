#!/usr/bin/env python3
"""Relocation regression tests: no live Agent or /opt/dsm modifications."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from instance_agent_relocation_gate import require_unlocked, active_relocation
from instance_agent_relocation_repository import InstanceAgentRelocationRepository, RelocationConflict


class AgentRelocationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(self.root / "test.db")))
        self.backend.initialize()
        self.repo = InstanceAgentRelocationRepository(self.backend, ROOT)
        with self.backend.transaction() as c:
            for node, role in (
                ("controller-node", "controller"), ("controller-2-node", "controller"), ("source-node", "agent"),
                ("target-node", "agent"), ("third-node", "agent"),
            ):
                c.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                          (node, node, role, "active"))
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES ('ctrl-1','controller-node','Controller')")
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES ('ctrl-2','controller-2-node','Other')")
            for agent, ctrl, node in (
                ("source-agent", "ctrl-1", "source-node"),
                ("target-agent", "ctrl-1", "target-node"),
            ):
                c.execute(
                    "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                    (agent, ctrl, node, agent, "active"),
                )
            c.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (1,'ctrl-1','Customer','active')")
            metadata = {"agent_id": "source-agent", "resource_profile_id": "low",
                        "network": {"ports": {"game": 24000}}, "custom": "preserved"}
            c.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,agent_id,controller_id,customer_id,"
                "runtime_id,game_version,build_id,metadata_json,manifest_path) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("server-1", "source-node", "dayz", "DayZ", "online",
                 "source-agent", "ctrl-1", 1, "dayz.stable", "stable", "", json.dumps(metadata),
                 "/dsm/instances/source-node/dayz/server-1/.dsm/instance-metadata.json"),
            )
            c.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit) "
                "VALUES ('contract-1',1,'dayz','active',1)"
            )
            c.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) "
                "VALUES ('server-1','contract-1')"
            )
            c.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port,bind_address) "
                "VALUES ('server-1','source-node','game','udp',24000,'0.0.0.0')"
            )
            c.execute(
                "INSERT INTO agent_port_ranges(agent_id,protocol,start_port,end_port,status) "
                "VALUES ('target-agent','udp',25000,25040,'active')"
            )
            c.execute(
                "INSERT INTO backup_policies(policy_id,instance_id,agent_id,enabled,mode,consistency,"
                "compression,interval_seconds,retention_count,include_json,exclude_json,revision,checksum,created_at,updated_at) "
                "VALUES ('policy-1','server-1','source-agent',1,'full','live','gzip',86400,7,'[]','[]',1,'abc',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        self.source = [{"name": "game", "protocol": "udp", "port": 24000, "bind_address": "0.0.0.0"}]
        self.target = [{"name": "game", "protocol": "udp", "port": 25000, "bind_address": "0.0.0.0"}]
        self.plan = {
            "instance_id": "server-1", "source_agent_id": "source-agent", "source_node_id": "source-node",
            "target_agent_id": "target-agent", "target_node_id": "target-node",
            "source_ports": self.source, "target_ports": self.target, "source_running": True,
            "source_manifest_path": "/dsm/instances/source-node/dayz/server-1/.dsm/instance-metadata.json",
            "target_manifest_path": "/dsm/instances/target-node/dayz/server-1/.dsm/instance-metadata.json",
            "game_id": "dayz", "runtime_id": "dayz.stable",
        }

    def enqueue(self):
        with patch.object(self.repo, "preflight", return_value=self.plan), patch.object(
            self.repo, "_network_plan", return_value=self.target
        ):
            return self.repo.enqueue("server-1", "target-agent",
                                     requested_by="admin@example.com", confirmation="server-1")

    def test_active_relocation_blocks_destructive_delete_and_retry(self):
        from dashboard_repository import DashboardRepository
        item = self.enqueue()
        repo = DashboardRepository(self.backend)
        with self.assertRaisesRegex(RuntimeError, "migration in progress"):
            repo.delete_instance("server-1")
        with self.assertRaisesRegex(RuntimeError, "migration in progress"):
            repo.reserve_retry("server-1", "source-node", "dayz")
        with self.backend.connect() as c:
            self.assertEqual(
                c.execute("SELECT count(*) FROM instances WHERE id='server-1'").fetchone()[0], 1,
            )

    def test_reconcile_lease_blocks_duplicate_heartbeat_side_effects(self):
        item = self.enqueue()
        self.repo._set(item["relocation_id"], lease_until=9999999999, lease_token="other-worker")
        with patch.object(self.repo, "_lifecycle") as lifecycle:
            state = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(state["status"], "queued")
        lifecycle.assert_not_called()
        self.repo._set(item["relocation_id"], lease_until=0, lease_token=None)
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "stopping")

    def test_same_host_fingerprint_blocks_cross_agent_move(self):
        with self.backend.transaction() as c:
            for agent in ("source-agent", "target-agent"):
                c.execute(
                    "INSERT INTO agent_runtime_inventory(agent_id,capabilities_json,cpu_json,"
                    "storage_json,health_status,fingerprint,network_json) "
                    "VALUES (?,'{}','{}','{}','online','same-fingerprint','{}')",
                    (agent,),
                )
        with self.assertRaisesRegex(ValueError, "same host fingerprint"):
            self.repo._instance_and_agents("server-1", "target-agent")

    def test_schema_and_uncommitted_preview_leave_instance_untouched(self):
        with self.backend.connect() as c:
            tables = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'instance_agent_relocation%'"
            ).fetchall()}
            self.assertEqual(tables, {"instance_agent_relocations", "instance_agent_relocation_port_holds"})
            before = c.execute("SELECT agent_id,node_id,status FROM instances WHERE id='server-1'").fetchone()
        with self.assertRaises(ValueError):
            self.repo.enqueue("server-1", "target-agent", requested_by="admin",
                              confirmation="wrong")
        with self.backend.connect() as c:
            after = c.execute("SELECT agent_id,node_id,status FROM instances WHERE id='server-1'").fetchone()
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(self.repo.list_for_instance("server-1"), [])

    def test_real_preflight_allocates_runtime_ports_and_checks_eligibility(self):
        with self.backend.transaction() as c:
            c.execute(
                "UPDATE instances SET manifest_path=? WHERE id='server-1'",
                (str(ROOT / "instances/source-node/dayz/server-1/.dsm/instance-metadata.json"),),
            )
        # Use the canonical DayZ runtime and real port allocator. Only the
        # transport health/capacity telemetry is mocked (no second Agent here).
        with patch(
            "instance_agent_relocation_repository.evaluate_agent_for_placement",
            return_value=SimpleNamespace(eligible=True, reasons=()),
        ), patch(
             "instance_agent_relocation_repository.AgentRuntimeRepository.snapshot",
            return_value={"health_status": "online", "capabilities": {"instance_relocation_fence_v1": True}},
        ), patch(
            "instance_agent_relocation_repository.occupied_ports_provider_for_backend",
            return_value=lambda *args: set(),
        ):
            result = self.repo.preflight("server-1", "target-agent")
        self.assertEqual(result["source_agent_id"], "source-agent")
        self.assertEqual(result["target_agent_id"], "target-agent")
        names = {port["name"] for port in result["target_ports"]}
        self.assertEqual(names, {"game", "game_aux", "steam_query", "battleye"})
        allocated = sorted({p["port"] for p in result["target_ports"]})
        self.assertEqual(allocated, [24000, 24002, 24003, 24004])

    def test_cross_controller_agent_rejected(self):
        with self.backend.transaction() as c:
            c.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) "
                "VALUES ('foreign-agent','ctrl-2','third-node','Foreign','active')"
            )
        with self.assertRaises(PermissionError):
            self.repo._instance_and_agents("server-1", "foreign-agent")

    def test_enqueue_reserves_destination_and_blocks_parallel_operations(self):
        item = self.enqueue()
        self.assertEqual(item["status"], "queued")
        self.assertEqual(item["target_ports"], self.target)
        self.assertEqual(item["requested_by"], "admin@example.com")
        with self.backend.connect() as c:
            instance = c.execute("SELECT agent_id,metadata_json FROM instances WHERE id='server-1'").fetchone()
            holds = c.execute(
                "SELECT node_id,port FROM instance_agent_relocation_port_holds WHERE relocation_id=?",
                (item["relocation_id"],),
            ).fetchall()
        self.assertEqual(instance["agent_id"], "source-agent")
        self.assertEqual([(r["node_id"], r["port"]) for r in holds], [("target-node", 25000)])
        self.assertIsNotNone(active_relocation(self.backend, "server-1"))
        with self.assertRaisesRegex(RuntimeError, "migration in progress"):
            require_unlocked(self.backend, "server-1", requested_by="customer")
        require_unlocked(self.backend, "server-1", requested_by="relocation:" + item["relocation_id"])
        with patch.object(self.repo, "preflight", return_value=self.plan):
            with self.assertRaises(RelocationConflict):
                self.repo.enqueue("server-1", "target-agent", requested_by="admin",
                                  confirmation="server-1")

    def test_cutover_and_safe_database_revert_preserve_exact_ports_metadata(self):
        item = self.enqueue()
        self.repo._set(item["relocation_id"], status="cutting_over", backup_sha256="a" * 64)
        item = self.repo.get(item["relocation_id"])
        with patch(
            "instance_agent_relocation_repository.AgentRuntimeRepository.snapshot",
            return_value={"health_status": "online"},
        ), patch(
            "instance_agent_relocation_repository.occupied_ports_provider_for_backend",
            return_value=lambda *args: set(),
        ):
            handoff = self.repo._cutover(item)
        self.assertEqual(handoff["status"], "provisioning")
        with self.backend.connect() as c:
            inst = c.execute("SELECT agent_id,node_id,metadata_json,manifest_path FROM instances WHERE id='server-1'").fetchone()
            port = c.execute("SELECT node_id,port FROM instance_ports WHERE instance_id='server-1'").fetchone()
            backup = c.execute("SELECT agent_id FROM backup_policies WHERE instance_id='server-1'").fetchone()
            held = c.execute(
                "SELECT node_id,port FROM instance_agent_relocation_port_holds WHERE relocation_id=?",
                (item["relocation_id"],),
            ).fetchall()
        self.assertEqual((inst["agent_id"], inst["node_id"]), ("target-agent", "target-node"))
        self.assertEqual((port["node_id"], port["port"]), ("target-node", 25000))
        self.assertEqual(backup["agent_id"], "target-agent")
        self.assertEqual(json.loads(inst["metadata_json"])["custom"], "preserved")
        self.assertEqual(json.loads(inst["metadata_json"])["network"]["ports"]["game"], 25000)
        self.assertEqual([(r["node_id"], r["port"]) for r in held], [("source-node", 24000)])
        self.repo._undo_cutover(handoff)
        with self.backend.connect() as c:
            inst = c.execute("SELECT agent_id,node_id,metadata_json,manifest_path FROM instances WHERE id='server-1'").fetchone()
            port = c.execute("SELECT node_id,port FROM instance_ports WHERE instance_id='server-1'").fetchone()
            backup = c.execute("SELECT agent_id FROM backup_policies WHERE instance_id='server-1'").fetchone()
        self.assertEqual((inst["agent_id"], inst["node_id"]), ("source-agent", "source-node"))
        self.assertEqual(json.loads(inst["metadata_json"])["network"]["ports"]["game"], 24000)
        self.assertEqual((port["node_id"], port["port"]), ("source-node", 24000))
        self.assertEqual(backup["agent_id"], "source-agent")

    def test_old_agent_stop_without_durable_fence_never_starts_transfer(self):
        item = self.enqueue()
        item = self.repo.reconcile(item["relocation_id"])
        self._complete(
            "agent_instance_commands", "command_id", item["stop_command_id"],
            status="completed",
            result_json=json.dumps({"status": "completed", "result": {"observed_state": "stopped"}}),
        )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "manual_recovery")
        self.assertIn("durable fencing", item["last_error"])
        self.assertIsNone(item["backup_job_id"])

    def test_destination_port_holds_are_visible_to_capacity_planning(self):
        from agent_port_repository import AgentPortRepository
        item = self.enqueue()
        holds = AgentPortRepository(self.backend).reservations("target-agent")
        matching = [row for row in holds if row["instance_id"] == item["relocation_id"]]
        self.assertEqual([(x["protocol"], x["port"]) for x in matching], [("udp", 25000)])

    def test_pre_cutover_rollback_restarts_source_before_releasing_port_hold(self):
        item = self.enqueue()
        item = self.repo.reconcile(item["relocation_id"])
        self._complete(
            "agent_instance_commands", "command_id", item["stop_command_id"],
            status="completed",
            result_json=json.dumps({"status": "completed", "result": {"observed_state": "stopped", "fenced": True}}),
        )
        item = self.repo._abort(item, "source backup failed")
        with patch.object(self.repo, "_lifecycle", side_effect=[
            {"command_id": "unpark-1", "status": "completed",
             "result": {"observed_state": "stopped"}},
            {"command_id": "restart-1", "status": "completed",
             "result": {"observed_state": "running"}},
        ]) as lifecycle:
            result = self.repo._rollback(item)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [call.args[1] for call in lifecycle.call_args_list],
            ["unfence", "start"],
        )
        self.assertIsNone(active_relocation(self.backend, "server-1"))
        with self.backend.connect() as c:
            self.assertEqual(c.execute(
                "SELECT count(*) FROM instance_agent_relocation_port_holds"
            ).fetchone()[0], 0)

    def _complete(self, table, identity_col, identity, **fields):
        with self.backend.transaction() as c:
            c.execute(
                f"UPDATE {table} SET " + ",".join(f"{k}=?" for k in fields)
                + f" WHERE {identity_col}=?",
                tuple(fields.values()) + (identity,),
            )

    def _archive(self):
        path = self.root / "source.tar.gz"
        manifest = {
            "kind": "CapivaraInstanceBackup", "backup_format": "capivara-instance",
            "source_instance": "server-1", "backup_id": "backup-1",
            "game_id": "dayz", "runtime_id": "dayz.stable",
        }
        with tarfile.open(path, "w:gz") as archive:
            data = json.dumps(manifest).encode()
            info = tarfile.TarInfo(".capivara-backup-manifest.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            data = b"world data"
            info = tarfile.TarInfo("world.txt")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _advance_to_restore(self):
        # Drives real repository/SQL/transfer code; mocks remote Agent replies.
        self.repo.transfers.spool = self.root / "spool"
        item = self.enqueue()
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "stopping")
        self._complete(
            "agent_instance_commands", "command_id", item["stop_command_id"],
            status="completed", result_json=json.dumps({"status": "completed", "result": {"observed_state": "stopped", "fenced": True}}),
        )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "backing_up")
        job = self.repo.backups.get_job(item["backup_job_id"])
        self.assertEqual(job["reason"], "agent_relocation:" + item["relocation_id"])
        archive, sha = self._archive()
        self._complete(
            "backup_jobs", "command_id", item["backup_job_id"], status="completed",
            backup_id="backup-1", sha256=sha, size_bytes=archive.stat().st_size,
            artifact_path="/tmp/backup-1.tar.gz",
        )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "exporting")
        export = self.repo.transfers.get(item["export_transfer_id"])
        path = self.repo.transfers._path(item["export_transfer_id"], export["filename"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.read_bytes())
        self._complete(
            "artifact_transfers", "transfer_id", item["export_transfer_id"],
            status="completed", sha256=sha,
            size_bytes=archive.stat().st_size, controller_path=str(path),
        )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "cutting_over")
        with patch(
            "instance_agent_relocation_repository.AgentRuntimeRepository.snapshot",
            return_value={"health_status": "online"},
        ), patch(
            "instance_agent_relocation_repository.occupied_ports_provider_for_backend",
            return_value=lambda *args: set(),
        ):
            item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "provisioning")
        with patch("instance_agent_relocation_repository.resolve_catalog_provisioning",
                   return_value=({"provider": "steam", "game": "dayz"}, {})), patch.object(
            self.repo.provisioning, "enqueue", return_value={"provisioning_id": "fake-destination"}
        ), patch.object(self.repo.provisioning, "snapshot", return_value={"status": "completed"}):
            item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "importing")
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "importing")
        transfer = self.repo.transfers.get(item["import_transfer_id"])
        self.assertEqual(transfer["sha256"], sha)
        self.assertEqual(transfer["status"], "queued")
        self._complete(
            "artifact_transfers", "transfer_id", item["import_transfer_id"],
            status="completed", transferred_bytes=archive.stat().st_size,
        )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "restoring")
        job = self.repo.backups.get_job(item["restore_job_id"])
        self.assertEqual(job["agent_id"], "target-agent")
        self.assertEqual(job["backup_id"], item["imported_backup_id"])
        return item

    def test_full_relocation_sequence_requires_verified_restore_and_health(self):
        item = self._advance_to_restore()
        self._complete("backup_jobs", "command_id", item["restore_job_id"], status="completed")
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "starting")
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "starting")
        self._complete(
            "agent_instance_commands", "command_id", item["start_command_id"],
            status="completed", result_json=json.dumps({"status": "completed", "result": {"observed_state": "running"}}),
        )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "verifying")
        with self.backend.transaction() as c:
            c.execute(
                "INSERT INTO agent_instance_runtime_health("
                "instance_id,agent_id,desired_state,observed_state,reconcile_status,"
                "health,operation_status,updated_at) VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                ("server-1", "target-agent", "running", "running", "in_sync",
                 "healthy", "idle"),
            )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "completed")
        self.assertEqual(self._ownership_for_test(), "target-agent")
        self.assertIsNone(active_relocation(self.backend, "server-1"))
        with self.backend.connect() as c:
            self.assertEqual(
                [(r["node_id"], r["port"]) for r in c.execute(
                    "SELECT node_id,port FROM instance_agent_relocation_port_holds "
                    "WHERE relocation_id=?", (item["relocation_id"],)
                )], [("source-node", 24000)],
            )

    def _ownership_for_test(self):
        with self.backend.connect() as c:
            return c.execute("SELECT agent_id FROM instances WHERE id='server-1'").fetchone()["agent_id"]

    def test_failed_restore_never_restarts_source_without_target_stop(self):
        item = self._advance_to_restore()
        self._complete("backup_jobs", "command_id", item["restore_job_id"],
                       status="failed", last_error="simulated destination restore failure")
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "rolling_back")
        self.assertEqual(self._ownership_for_test(), "target-agent")
        with patch.object(self.repo.provisioning, "snapshot", return_value={"status": "completed"}):
            item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(self._ownership_for_test(), "target-agent")
        self.assertIsNotNone(item["rollback_command_id"])
        self._complete(
            "agent_instance_commands", "command_id", item["rollback_command_id"],
            status="completed", result_json=json.dumps({"status": "completed", "result": {"observed_state": "stopped"}}),
        )
        with patch.object(self.repo.provisioning, "snapshot", return_value={"status": "completed"}):
            item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(self._ownership_for_test(), "source-agent")
        self.assertEqual(item["status"], "rolling_back")
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "rolling_back")
        unpark = self.repo._existing_lifecycle(item, "unfence", "source-agent")
        self.assertIsNotNone(unpark)
        self.assertIsNone(self.repo._existing_lifecycle(item, "start", "source-agent"))
        self._complete(
            "agent_instance_commands", "command_id", unpark["command_id"],
            status="completed",
            result_json=json.dumps({"status": "completed", "result": {"observed_state": "stopped"}}),
        )
        item = self.repo.reconcile(item["relocation_id"])
        source_start = self.repo._existing_lifecycle(item, "start", "source-agent")
        self.assertIsNotNone(source_start)
        self._complete(
            "agent_instance_commands", "command_id", source_start["command_id"],
            status="completed", result_json=json.dumps(
                {"status": "completed", "result": {"observed_state": "running"}}
            ),
        )
        item = self.repo.reconcile(item["relocation_id"])
        self.assertEqual(item["status"], "failed")
        with self.backend.connect() as c:
            self.assertEqual(
                c.execute("SELECT count(*) FROM instance_agent_relocation_port_holds "
                          "WHERE relocation_id=?", (item["relocation_id"],)).fetchone()[0], 0
            )

    def test_checksum_and_manifest_verification_blocks_tampering(self):
        manifest = {
            "kind": "CapivaraInstanceBackup", "backup_format": "capivara-instance",
            "source_instance": "server-1", "backup_id": "backup-1",
            "game_id": "dayz", "runtime_id": "dayz.stable",
        }
        path = self.root / "valid.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            encoded = json.dumps(manifest).encode()
            info = tarfile.TarInfo(".capivara-backup-manifest.json")
            info.size = len(encoded)
            archive.addfile(info, io.BytesIO(encoded))
            data = b"world data"
            info = tarfile.TarInfo("world.txt")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {
            "backup_sha256": digest, "instance_id": "server-1",
            "backup_id": "backup-1", "game_id": "dayz", "runtime_id": "dayz.stable",
        }
        self.repo._validate_artifact(path, record)
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.repo._validate_artifact(path, {**record, "backup_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.repo._validate_artifact(path, {**record, "backup_id": "other-backup"})


if __name__ == "__main__":
    unittest.main()
