#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"database",ROOT/"core"):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from core.minecraft_serverpack_pending_commit import build_pending_bundle_commit


def local_artifact(content_id:str,version:str,sha_char:str):
    return {
        "provider":"local",
        "serverpack_child_v1":True,
        "ephemeral_upload":True,
        "bundle_parent_content_id":"atm11",
        "bundle_member":f"mods/{content_id}.jar",
        "serverpack_loader":"neoforge",
        "serverpack_loader_version":version,
        "sha256":sha_char*64,
        "size_bytes":123,
    }


def bundle(version_id:str,loader_version:str,sha_char:str):
    artifact=local_artifact("mod-a",loader_version,sha_char)
    return {
        "provider":"local",
        "provider_project_id":"cf-1148445",
        "provider_version_id":version_id,
        "minecraft_version":"26.1.2",
        "loader_id":"neoforge",
        "loader_version":loader_version,
        "manifest_kind":"serverpack-local-v1",
        "members":[{"content_id":"mod-a","path":"mods/mod-a.jar","required":True,"artifact":artifact}],
        "override_roots":["server-overrides"],
    }


def parent(version_id:str):
    return {
        "instance_id":"pr855-controller-atomic",
        "content_id":"atm11",
        "content_type":"modpack",
        "provider":"local",
        "version":version_id,
        "target":"modpacks/atm11",
        "artifact":{
            "provider":"local","package_id":f"quarantine/{version_id}.zip",
            "filename":f"{version_id}.zip","archive":True,"ephemeral_upload":True,
        },
        "metadata":{},
    }


def child(version_id:str,loader_version:str,sha_char:str):
    return {
        "instance_id":"pr855-controller-atomic",
        "content_id":"mod-a",
        "content_type":"mod",
        "provider":"local",
        "version":version_id,
        "target":"mods/mod-a",
        "artifact":local_artifact("mod-a",loader_version,sha_char),
        "metadata":{},
    }


class AtomicPendingPublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="pr855-controller-atomic-")
        self.backend=create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name)/"db.sqlite"),
        ))
        self.backend.initialize()
        with self.backend.transaction() as c:
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("ctrl-node","Controller","controller"))
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"))
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("ctrl","ctrl-node","Controller"))
            c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("pr839-isolated-agent","ctrl","agent-node","Agent","active"))
            customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("ctrl","Customer"))
            c.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id,game_version,build_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("pr855-controller-atomic","agent-node","minecraft","minecraft.java.neoforge","Lab","stopped","ctrl","pr839-isolated-agent",customer.lastrowid,"26.1.2","26.1.2.94"),
            )
            c.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                ("pr855-controller-atomic","agent-node","game","tcp",25582),
            )
        self.content=ContentRepository(self.backend)
        self.content.initialize()
        first=self.content.put_bundle(
            parent("old"),
            bundle("old","26.1.2.94","a"),
            [child("old","26.1.2.94","a")],
            requested_by="customer",
        )
        self.assertEqual(first["bundle_revision"],1)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def pending(self,fingerprint="c"*64):
        new_bundle=bundle("new","26.1.2.109","b")
        new_parent=parent("new")
        new_child=child("new","26.1.2.109","b")
        return build_pending_bundle_commit(
            instance_id="pr855-controller-atomic",
            content_id="atm11",
            transfer_id="transfer-atomic",
            migration_plan_sha256=fingerprint,
            expected_previous_revision=1,
            parent=new_parent,
            bundle=new_bundle,
            children=[new_child],
            requested_by="customer",
        )

    def enqueue(self,pending):
        repo=AgentInstanceProvisioningRepository(self.backend)
        state=repo.enqueue(
            agent_id="pr839-isolated-agent",
            instance_id="pr855-controller-atomic",
            environment_id="minecraft.java.neoforge",
            selector="26.1.2@26.1.2.109",
            selection={"runtime_definition":"minecraft.java.neoforge","version":"26.1.2","build":"26.1.2.109"},
            configuration={
                "minecraft_serverpack_migration":{
                    "kind":"MinecraftServerPackMigration",
                    "instance_id":"pr855-controller-atomic",
                },
                "minecraft_serverpack_pending_bundle":pending,
            },
            desired_state="stopped",
            requested_by="customer",
        )
        return repo,state

    def completed(self,state,pending,*,fingerprint=None):
        fp=fingerprint or pending["migration_plan_sha256"]
        return {
            "provisioning_id":state["provisioning_id"],
            "instance_id":"pr855-controller-atomic",
            "status":"completed",
            "progress":100,
            "current_step":"completed",
            "minecraft_serverpack_migration":{
                "status":"completed",
                "instance_id":"pr855-controller-atomic",
                "content_id":"atm11",
                "transfer_id":"transfer-atomic",
                "migration_plan_sha256":fp,
                "commit":{
                    "status":"committed",
                    "journal":{
                        "phase":"committed",
                        "migration_plan_sha256":fp,
                    },
                },
            },
        }

    def test_completed_agent_result_publishes_bundle_in_same_completion_transaction(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],1)
        completed=repo.apply_result(
            "pr839-isolated-agent",
            self.completed(state,pending),
        )
        self.assertEqual(completed["status"],"completed")
        history=self.content.bundle_history("pr855-controller-atomic","atm11")
        self.assertEqual(history[0]["revision"],2)
        self.assertEqual(history[0]["loader_version"],"26.1.2.109")
        publication=completed["result"]["controller_bundle_publication"]
        self.assertEqual(publication["status"],"published")
        self.assertEqual(publication["previous_bundle_revision"],1)
        self.assertEqual(publication["bundle_revision"],2)

    def test_mismatched_agent_fingerprint_rolls_back_job_completion_and_bundle_publication(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        with self.assertRaisesRegex(Exception,"migration_plan_sha256 mismatch"):
            repo.apply_result(
                "pr839-isolated-agent",
                self.completed(state,pending,fingerprint="d"*64),
            )
        snapshot=repo.snapshot(state["provisioning_id"])
        self.assertEqual(snapshot["status"],"queued")
        history=self.content.bundle_history("pr855-controller-atomic","atm11")
        self.assertEqual(history[0]["revision"],1)
        self.assertEqual(history[0]["loader_version"],"26.1.2.94")

    def test_stale_bundle_revision_rolls_back_job_completion(self):
        pending=self.pending()
        repo,state=self.enqueue(pending)
        self.content.put_bundle(
            parent("other"),
            bundle("other","26.1.2.94","e"),
            [child("other","26.1.2.94","e")],
            requested_by="other",
        )
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],2)
        with self.assertRaisesRegex(Exception,"revision changed"):
            repo.apply_result(
                "pr839-isolated-agent",
                self.completed(state,pending),
            )
        self.assertEqual(repo.snapshot(state["provisioning_id"])["status"],"queued")
        self.assertEqual(self.content.bundle_history("pr855-controller-atomic","atm11")[0]["revision"],2)


if __name__=="__main__":
    unittest.main()
