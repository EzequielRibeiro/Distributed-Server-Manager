#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/"dashboard",ROOT/"database",ROOT/"core"):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from core.minecraft_serverpack_pending_commit import build_pending_bundle_commit
import minecraft_serverpack_migration_service as migration_service


def artifact(content_id,loader,fill):
    return {
        "provider":"local",
        "serverpack_child_v1":True,
        "ephemeral_upload":True,
        "bundle_parent_content_id":"atm11",
        "bundle_member":f"mods/{content_id}.jar",
        "serverpack_loader":"neoforge",
        "serverpack_loader_version":loader,
        "sha256":fill*64,
        "size_bytes":321,
    }


def bundle(version_id,loader,fill):
    item=artifact("mod-a",loader,fill)
    return {
        "provider":"local",
        "provider_project_id":"cf-1148445",
        "provider_version_id":version_id,
        "minecraft_version":"26.1.2",
        "loader_id":"neoforge",
        "loader_version":loader,
        "manifest_kind":"serverpack-local-v1",
        "members":[{"content_id":"mod-a","path":"mods/mod-a.jar","required":True,"artifact":item}],
        "override_roots":["config","kubejs"],
    }


def parent(version_id):
    return {
        "instance_id":"pr855-controller-e2e",
        "content_id":"atm11",
        "content_type":"modpack",
        "provider":"local",
        "version":version_id,
        "target":"modpacks/atm11",
        "artifact":{
            "provider":"local",
            "package_id":f"quarantine/{version_id}.zip",
            "filename":f"{version_id}.zip",
            "archive":True,
            "ephemeral_upload":True,
        },
        "metadata":{},
    }


def child(version_id,loader,fill):
    return {
        "instance_id":"pr855-controller-e2e",
        "content_id":"mod-a",
        "content_type":"mod",
        "provider":"local",
        "version":version_id,
        "target":"mods/mod-a",
        "artifact":artifact("mod-a",loader,fill),
        "metadata":{},
    }


class Workspace:
    def __init__(self):
        self.context={
            "id":"pr855-controller-e2e",
            "agent_id":"pr839-isolated-agent",
            "game_id":"minecraft",
            "runtime_id":"minecraft.java.neoforge",
            "game_version":"26.1.2",
            "build_id":"26.1.2.94",
        }
    def require(self,user,instance_id,permission):
        if instance_id!="pr855-controller-e2e":
            raise AssertionError(instance_id)
        if permission!="instance.update":
            raise AssertionError(permission)
        return dict(self.context)


class Uploads:
    def __init__(self,payload):
        self.payload=payload
    def prepare_staged_loader_migration(self,user,transfer_id,body,fingerprint):
        if transfer_id!="transfer-e2e" or fingerprint!="c"*64:
            raise AssertionError("unexpected migration evidence")
        return self.payload


class ControllerServerPackFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="pr855-controller-e2e-")
        self.backend=create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name)/"capivara.db"),
        ))
        self.backend.initialize()
        with self.backend.transaction() as c:
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("ctrl-node","Controller","controller"))
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"))
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("ctrl","ctrl-node","Controller"))
            c.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("pr839-isolated-agent","ctrl","agent-node","Agent","active"),
            )
            customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("ctrl","Customer"))
            c.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id,game_version,build_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("pr855-controller-e2e","agent-node","minecraft","minecraft.java.neoforge","Lab","stopped","ctrl","pr839-isolated-agent",customer.lastrowid,"26.1.2","26.1.2.94"),
            )
            c.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                ("pr855-controller-e2e","agent-node","game","tcp",25582),
            )
        self.content=ContentRepository(self.backend);self.content.initialize()
        first=self.content.put_bundle(
            parent("old"),
            bundle("old","26.1.2.94","a"),
            [child("old","26.1.2.94","a")],
            requested_by="customer",
        )
        self.assertEqual(first["bundle_revision"],1)

        new_parent=parent("new")
        new_bundle=bundle("new","26.1.2.109","b")
        new_child=child("new","26.1.2.109","b")
        pending=build_pending_bundle_commit(
            instance_id="pr855-controller-e2e",
            content_id="atm11",
            transfer_id="transfer-e2e",
            migration_plan_sha256="c"*64,
            expected_previous_revision=1,
            parent=new_parent,
            bundle=new_bundle,
            children=[new_child],
            requested_by="customer",
        )
        self.prepared={
            "kind":"MinecraftServerPackPreparedMigration",
            "install_allowed":False,
            "migration":{
                "valid":True,
                "install_allowed":False,
                "migration_plan_sha256":"c"*64,
                "evidence":{
                    "instance_id":"pr855-controller-e2e",
                    "content_id":"atm11",
                    "transfer_id":"transfer-e2e",
                    "incoming_sha256":"d"*64,
                    "filename":"ServerFiles-0.9.0-beta.zip",
                    "archive_size_bytes":518936896,
                    "serverpack_prefix":"",
                    "serverpack_mod_count":254,
                    "serverpack_override_dirs":["config","kubejs"],
                    "previous_bundle_revision":1,
                    "previous_manifest_sha256":self.content.bundle_history("pr855-controller-e2e","atm11")[0]["manifest_sha256"],
                    "from_loader_version":"26.1.2.94",
                    "target_loader_version":"26.1.2.109",
                    "minecraft_version":"26.1.2",
                    "provider_project_id":"cf-1148445",
                    "provider_version_id":"new",
                },
            },
            "pending_bundle_commit":pending,
            "candidate_bundle_revision":2,
        }

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_enqueue_then_agent_commit_publishes_exact_pending_revision(self):
        service=migration_service.MinecraftServerPackMigrationService.__new__(
            migration_service.MinecraftServerPackMigrationService
        )
        service.backend=self.backend
        service.root=ROOT
        service.workspace=Workspace()
        service.uploads=Uploads(self.prepared)
        selection={
            "runtime_definition":"minecraft.java.neoforge",
            "environment_id":"minecraft.java.neoforge",
            "game":"minecraft",
            "version":"26.1.2",
            "build":"26.1.2.109",
            "provider":"http",
            "installer":{"type":"java_jar"},
            "asset":{"sha256":"e"*64,"url":"https://maven.neoforged.net/example.jar"},
        }
        body={
            "instance_id":"pr855-controller-e2e",
            "transfer_id":"transfer-e2e",
            "content_id":"atm11",
            "content_type":"modpack",
            "metadata":{"serverpack":{"format":"official-serverpack-v1"}},
        }
        with patch.dict(os.environ,{
            "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES",
        },clear=False),patch.object(
            migration_service,
            "resolve_catalog_provisioning",
            return_value=(selection,{"catalog_runtime_id":"minecraft.java.neoforge"}),
        ):
            accepted=service.request(
                {"username":"customer"},"transfer-e2e",body,"c"*64
            )
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["status"],"queued")
        self.assertFalse(accepted["pending_bundle"]["publish_allowed"])
        self.assertEqual(self.content.bundle_history("pr855-controller-e2e","atm11")[0]["revision"],1)

        jobs=AgentInstanceProvisioningRepository(self.backend)
        state=jobs.snapshot(accepted["provisioning_id"])
        request=state["request"]
        migration=request["configuration"]["minecraft_serverpack_migration"]
        self.assertEqual(migration["migration_plan_sha256"],"c"*64)
        self.assertEqual(
            request["configuration"]["minecraft_serverpack_pending_bundle"]["candidate_sha256"],
            self.prepared["pending_bundle_commit"]["candidate_sha256"],
        )

        completed={
            "provisioning_id":accepted["provisioning_id"],
            "instance_id":"pr855-controller-e2e",
            "status":"completed",
            "progress":100,
            "current_step":"completed",
            "minecraft_serverpack_migration":{
                "status":"completed",
                "instance_id":"pr855-controller-e2e",
                "content_id":"atm11",
                "transfer_id":"transfer-e2e",
                "migration_plan_sha256":"c"*64,
                "from_loader_version":"26.1.2.94",
                "target_loader_version":"26.1.2.109",
                "commit":{
                    "status":"committed",
                    "journal":{
                        "phase":"committed",
                        "migration_plan_sha256":"c"*64,
                    },
                },
            },
        }
        final=jobs.apply_result("pr839-isolated-agent",completed)
        self.assertEqual(final["status"],"completed")
        history=self.content.bundle_history("pr855-controller-e2e","atm11")
        self.assertEqual(history[0]["revision"],2)
        self.assertEqual(history[0]["loader_version"],"26.1.2.109")
        self.assertEqual(
            final["result"]["controller_bundle_publication"]["candidate_sha256"],
            self.prepared["pending_bundle_commit"]["candidate_sha256"],
        )
        with self.backend.connect() as connection:
            row=connection.execute(
                "SELECT game_version,build_id FROM instances WHERE id=?",
                ("pr855-controller-e2e",),
            ).fetchone()
        self.assertEqual(row["game_version"],"26.1.2")
        self.assertEqual(row["build_id"],"26.1.2.109")


if __name__=="__main__":
    unittest.main()
