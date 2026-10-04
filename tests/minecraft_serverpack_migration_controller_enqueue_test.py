#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/"dashboard",ROOT/"database",ROOT/"core",ROOT/"agents/linux/runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

import minecraft_serverpack_migration_service as module
from minecraft_serverpack_migration_contract import validate_minecraft_serverpack_migration


class Workspace:
    def __init__(self,context):
        self.context=dict(context)
        self.calls=[]
    def require(self,user,instance_id,permission):
        self.calls.append((instance_id,permission))
        return dict(self.context)


class Uploads:
    def __init__(self,prepared):
        self.prepared=prepared
        self.calls=[]
    def prepare_staged_loader_migration(self,user,transfer_id,body,fingerprint):
        self.calls.append((transfer_id,dict(body),fingerprint))
        return self.prepared


class Jobs:
    last=None
    returned=None
    def __init__(self,backend):
        self.backend=backend
        self.kwargs=None
        Jobs.last=self
    def initialize(self):
        return None
    def enqueue(self,**kwargs):
        self.kwargs=kwargs
        if Jobs.returned is not None:
            return Jobs.returned
        request={
            "configuration":dict(kwargs["configuration"]),
            "content":{"action":"ensure","selection":dict(kwargs["selection"])},
        }
        return {
            "provisioning_id":"instance-provision-pr855",
            "status":"queued",
            "request":request,
        }


def prepared():
    fingerprint="c"*64
    pending={
        "kind":"MinecraftServerPackPendingBundleCommit",
        "schema_version":1,
        "instance_id":"pr855-customer-flow",
        "content_id":"atm11",
        "transfer_id":"transfer-pr855",
        "migration_plan_sha256":fingerprint,
        "expected_previous_revision":4,
        "parent":{"instance_id":"pr855-customer-flow","content_id":"atm11"},
        "bundle":{"provider":"local"},
        "children":[{"instance_id":"pr855-customer-flow","content_id":"mod-a"}],
        "requested_by":"customer",
        "candidate_sha256":"d"*64,
        "publish_allowed":False,
    }
    evidence={
        "instance_id":"pr855-customer-flow",
        "content_id":"atm11",
        "transfer_id":"transfer-pr855",
        "incoming_sha256":"a"*64,
        "filename":"ServerFiles-0.9.0-beta.zip",
        "archive_size_bytes":518936896,
        "serverpack_prefix":"",
        "serverpack_mod_count":254,
        "serverpack_override_dirs":["config","kubejs"],
        "previous_bundle_revision":4,
        "previous_manifest_sha256":"b"*64,
        "from_loader_version":"26.1.2.94",
        "target_loader_version":"26.1.2.109",
        "minecraft_version":"26.1.2",
        "provider_project_id":"cf-1148445",
        "provider_version_id":"file-new",
    }
    return {
        "kind":"MinecraftServerPackPreparedMigration",
        "install_allowed":False,
        "migration":{
            "valid":True,
            "install_allowed":False,
            "migration_plan_sha256":fingerprint,
            "evidence":evidence,
            "requires_verified_backup":True,
            "requires_exclusive_instance_lock":True,
        },
        "pending_bundle_commit":pending,
        "candidate_bundle_revision":5,
    }


class ControllerMigrationEnqueueTest(unittest.TestCase):
    def setUp(self):
        Jobs.returned=None
        self.context={
            "id":"pr855-customer-flow",
            "agent_id":"pr839-isolated-agent",
            "game_id":"minecraft",
            "runtime_id":"minecraft.java.neoforge",
            "game_version":"26.1.2",
            "build_id":"26.1.2.94",
        }
        self.service=module.MinecraftServerPackMigrationService.__new__(
            module.MinecraftServerPackMigrationService
        )
        self.service.backend=object()
        self.service.root=ROOT
        self.service.workspace=Workspace(self.context)
        self.service.uploads=Uploads(prepared())
        self.body={
            "instance_id":"pr855-customer-flow",
            "transfer_id":"transfer-pr855",
            "content_id":"atm11",
            "content_type":"modpack",
            "metadata":{"serverpack":{"format":"official-serverpack-v1"}},
        }

    def resolver(self,**kwargs):
        self.assertEqual(kwargs["environment_id"],"minecraft.java.neoforge")
        self.assertEqual(kwargs["selector"],"26.1.2@26.1.2.109")
        return ({
            "runtime_definition":"minecraft.java.neoforge",
            "environment_id":"minecraft.java.neoforge",
            "game":"minecraft",
            "version":"26.1.2",
            "build":"26.1.2.109",
            "provider":"http",
            "installer":{"type":"java_jar"},
            "asset":{"sha256":"e"*64,"url":"https://maven.neoforged.net/example.jar"},
        },{"catalog_runtime_id":"minecraft.java.neoforge"})

    def test_revalidated_candidate_is_enqueued_without_publishing_bundle(self):
        with patch.dict(os.environ,{
            "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES",
        },clear=False),patch.object(
            module,"resolve_catalog_provisioning",side_effect=self.resolver
        ),patch.object(module,"AgentInstanceProvisioningRepository",Jobs):
            result=self.service.request(
                {"username":"customer"},
                "transfer-pr855",
                self.body,
                "c"*64,
            )
        self.assertTrue(result["accepted"])
        self.assertTrue(result["homologation_only"])
        self.assertEqual(result["status"],"queued")
        self.assertFalse(result["pending_bundle"]["publish_allowed"])
        self.assertEqual(result["pending_bundle"]["candidate_bundle_revision"],5)
        self.assertIn(("pr855-customer-flow","instance.update"),self.service.workspace.calls)

        kwargs=Jobs.last.kwargs
        self.assertEqual(kwargs["desired_state"],"stopped")
        self.assertEqual(kwargs["selector"],"26.1.2@26.1.2.109")
        config=kwargs["configuration"]
        migration=config["minecraft_serverpack_migration"]
        self.assertEqual(migration["archive_sha256"],"a"*64)
        self.assertEqual(migration["previous_bundle_revision"],4)
        self.assertEqual(migration["from_loader_version"],"26.1.2.94")
        self.assertEqual(migration["target_loader_version"],"26.1.2.109")
        self.assertFalse(migration["install_allowed"])
        self.assertEqual(
            config["minecraft_serverpack_pending_bundle"]["candidate_sha256"],
            "d"*64,
        )
        self.assertEqual(
            kwargs["selection"]["install_dir"],
            migration["isolated_install_dir"],
        )
        validated=validate_minecraft_serverpack_migration(
            migration,
            instance_id="pr855-customer-flow",
        )
        self.assertEqual(validated["serverpack_mod_count"],254)

    def test_gate_refuses_production_instance_or_agent_before_upload_preparation(self):
        cases=(
            {**self.context,"id":"cli-000001-minecraft-005"},
            {**self.context,"agent_id":"agent-5d320c393c9dc0f8e36e"},
        )
        for context in cases:
            with self.subTest(context=context):
                service=module.MinecraftServerPackMigrationService.__new__(
                    module.MinecraftServerPackMigrationService
                )
                service.backend=object();service.root=ROOT
                service.workspace=Workspace(context)
                service.uploads=Uploads(prepared())
                with patch.dict(os.environ,{
                    "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES",
                },clear=False),self.assertRaisesRegex(
                    module.MinecraftServerPackMigrationRequestError,
                    "restricted to PR855 homologation",
                ):
                    service.request(
                        {"username":"customer"},
                        "transfer-pr855",
                        {**self.body,"instance_id":context["id"]},
                        "c"*64,
                    )
                self.assertEqual(service.uploads.calls,[])

    def test_gate_requires_explicit_environment_switch(self):
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(
            module.MinecraftServerPackMigrationRequestError,
            "restricted to PR855 homologation",
        ):
            self.service.request(
                {"username":"customer"},"transfer-pr855",self.body,"c"*64
            )
        self.assertEqual(self.service.uploads.calls,[])

    def test_changed_live_loader_after_preview_is_rejected_before_enqueue(self):
        self.service.workspace.context["build_id"]="26.1.2.95"
        with patch.dict(os.environ,{
            "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES",
        },clear=False),patch.object(
            module,"AgentInstanceProvisioningRepository",Jobs
        ),self.assertRaisesRegex(
            module.MinecraftServerPackMigrationRequestError,
            "loader identity changed",
        ):
            self.service.request(
                {"username":"customer"},"transfer-pr855",self.body,"c"*64
            )
        self.assertIsNone(Jobs.last)

    def test_existing_different_active_provisioning_is_not_reported_as_accepted(self):
        Jobs.returned={
            "provisioning_id":"other-job",
            "status":"running",
            "request":{
                "configuration":{"minecraft_version_update":{"target_build":"other"}}
            },
        }
        with patch.dict(os.environ,{
            "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES",
        },clear=False),patch.object(
            module,"resolve_catalog_provisioning",side_effect=self.resolver
        ),patch.object(module,"AgentInstanceProvisioningRepository",Jobs),self.assertRaisesRegex(
            module.MinecraftServerPackMigrationRequestError,
            "different active provisioning",
        ):
            self.service.request(
                {"username":"customer"},"transfer-pr855",self.body,"c"*64
            )


if __name__=="__main__":
    unittest.main()
