"""One customer HTTP action to Agent physical swap, Controller CAS and 493-state ACK.

Disposable SQLite, loopback HTTP, temporary Agent filesystem only.
The NeoForge JVM bootstrap has its own official 291-mod CI smoke; this test
exercises the joined transaction with a simulated readiness result.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
from pathlib import Path
import sys
import tarfile
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT/"core", ROOT/"dashboard", ROOT/"database",
             ROOT/"agents/linux/runtime", ROOT/"agents/common", ROOT/"tests"):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

import dashboard.minecraft_serverpack_migration_service as migration_service
import instance_runtime
import minecraft_serverpack_pending_publication_atomic_test as atomic_fixture
import tests.minecraft_serverpack_authenticated_493_http_e2e_test as scale_fixture
from tests.minecraft_serverpack_migration_http_enqueue_test import MigrationEnqueueHTTPTest
from tests.minecraft_serverpack_authenticated_493_http_e2e_test import LargeRealCredentialHTTP
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from core.minecraft_serverpack_pending_commit import build_pending_bundle_commit
from minecraft_serverpack_physical_manifest import attest_serverpack_mods
from minecraft_serverpack_migration_transaction import execute_minecraft_serverpack_migration
from minecraft_serverpack_report_outbox import read_serverpack_report_delivery
from minecraft_serverpack_content_promotion import promote_verified_sources
from minecraft_serverpack_local_state_promotion import promote_local_state_snapshot
from minecraft_serverpack_content_receipt import confirmed_serverpack_receipt
from minecraft_serverpack_content_convergence import (
    verify_serverpack_content_convergence, ServerPackConvergenceError)


class SingleCustomerActionToAuthenticatedAckE2E(LargeRealCredentialHTTP):
    """Real customer route, Agent transaction and authenticated heartbeat joined."""

    def setUp(self):
        self.client_count=0
        self.physical_transaction=None
        self.accepted=None
        def actual_loader(value):
            return {"26.1.2.94":"26.1.2.109","26.1.2.109":"26.1.2.126"}.get(value,value)
        base_bundle=scale_fixture.bundle
        base_child=scale_fixture.child
        base_artifact=scale_fixture.local_artifact
        def mapped_bundle(version_id,loader,fill):
            return base_bundle(version_id,actual_loader(loader),fill)
        def mapped_child(version_id,loader,fill):
            return base_child(version_id,actual_loader(loader),fill)
        def mapped_artifact(cid,loader,fill):
            return base_artifact(cid,actual_loader(loader),fill)

        def client_enqueue(fixture,pending,*,production=False):
            self.client_count+=1
            self.assertEqual(self.client_count,1)
            self.assertEqual(pending["expected_previous_revision"],2)
            iid=pending["instance_id"]
            # Bind the frozen candidate to real filesystem-verifiable synthetic bytes.
            for item in pending["children"]:
                cid=item["content_id"]
                raw=b"offline-simulated-jar-"+cid.encode()
                item["artifact"]["sha256"]=hashlib.sha256(raw).hexdigest()
                item["artifact"]["size_bytes"]=len(raw)
                item["artifact"]["filename"]=cid+".jar"
            member_index={m["content_id"]:m for m in pending["bundle"]["members"]}
            for item in pending["children"]:
                member_index[item["content_id"]]["artifact"]=dict(item["artifact"])
            rebound=build_pending_bundle_commit(**{key:pending[key] for key in (
                "instance_id","content_id","transfer_id",
                "migration_plan_sha256","expected_previous_revision",
                "parent","bundle","children","requested_by")})
            pending.clear()
            pending.update(rebound)
            aid="pr839-isolated-agent"
            target=pending["bundle"]["loader_version"]
            old="26.1.2.109"
            with fixture.backend.transaction() as conn:
                conn.execute("UPDATE instances SET build_id=? WHERE id=?",(old,iid))
            previous=fixture.content.bundle_history(iid,"atm11")[0]
            self.assertEqual(previous["revision"],2)
            prepared={
              "kind":"MinecraftServerPackPreparedMigration",
              "install_allowed":False,
              "migration":{
                "valid":True,"install_allowed":False,
                "migration_plan_sha256":pending["migration_plan_sha256"],
                "evidence":{
                    "instance_id":iid,"content_id":"atm11",
                    "transfer_id":pending["transfer_id"],
                    "incoming_sha256":"d"*64,
                    "filename":"ServerFiles-0.14.0-beta.zip",
                    "archive_size_bytes":823456,
                    "serverpack_prefix":"",
                    "serverpack_mod_count":len(pending["children"]),
                    "serverpack_override_dirs":["config","kubejs"],
                    "previous_bundle_revision":2,
                    "previous_manifest_sha256":previous["manifest_sha256"],
                    "from_loader_version":old,
                    "target_loader_version":target,
                    "minecraft_version":"26.1.2",
                    "provider_project_id":"cf-1148445",
                    "provider_version_id":"0.14.0-beta",
                },
              },
              "pending_bundle_commit":pending,
              "candidate_bundle_revision":3,
            }
            service=migration_service.MinecraftServerPackMigrationService.__new__(
                migration_service.MinecraftServerPackMigrationService)
            service.backend=fixture.backend
            service.root=ROOT
            class Workspace:
                def require(_s,user,instance,permission):
                    assert instance==iid and permission=="instance.update"
                    return {"id":iid,"game_id":"minecraft",
                            "agent_id":aid,"runtime_id":"minecraft.java.neoforge",
                            "build_id":old}
            class Upload:
                def prepare_staged_loader_migration(_s,user,transfer,body,sha):
                    assert transfer==pending["transfer_id"]
                    assert sha==pending["migration_plan_sha256"]
                    return prepared
            service.workspace=Workspace()
            service.uploads=Upload()
            selector={
                "runtime_definition":"minecraft.java.neoforge",
                "environment_id":"minecraft.java.neoforge",
                "game":"minecraft","version":"26.1.2",
                "build":target,"provider":"http",
                "installer":{"type":"java_jar"},
                "asset":{"sha256":"e"*64,"url":"https://maven.neoforged.net/example.jar"},
            }
            policy={
                "CAPIVARA_SERVERPACK_MIGRATION_MODE":"production",
                "CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":"AUTHORIZED",
                "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":iid,
                "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":aid,
            }
            with patch.dict(os.environ,policy), patch.object(
                migration_service,"resolve_catalog_provisioning",
                return_value=(selector,{"catalog_runtime_id":"minecraft.java.neoforge"}),
            ):
                server,thread,patcher,_=MigrationEnqueueHTTPTest()._server(
                    lambda calls: lambda backend,root:service)
                try:
                    data={
                        "instance_id":iid,
                        "transfer_id":pending["transfer_id"],
                        "content_id":"atm11",
                        "content_type":"modpack",
                        "metadata":{"serverpack":{"format":"official-serverpack-v1"}},
                        "migration_plan_sha256":pending["migration_plan_sha256"],
                    }
                    req=urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/api/customer/instance/workspace/content/upload/migration/enqueue",
                        method="POST",data=json.dumps(data).encode("utf-8"),
                        headers={"Content-Type":"application/json"})
                    with urllib.request.urlopen(req,timeout=10) as response:
                        self.assertEqual(response.status,202)
                        self.accepted=json.load(response)["migration"]
                finally:
                    patcher.stop()
                    server.shutdown();server.server_close();thread.join(timeout=5)
            self.assertTrue(self.accepted["accepted"])
            self.assertFalse(self.accepted["pending_bundle"]["publish_allowed"])
            self.assertEqual(self.accepted["pending_bundle"]["expected_previous_revision"],2)
            self.assertEqual(fixture.content.bundle_history(iid,"atm11")[0]["revision"],2)
            jobs=AgentInstanceProvisioningRepository(fixture.backend)
            queued=jobs.snapshot(self.accepted["provisioning_id"])
            self.assertEqual(queued["status"],"queued")
            self.assertEqual(
                queued["request"]["configuration"]["minecraft_serverpack_pending_bundle"]["candidate_sha256"],
                pending["candidate_sha256"])
            self.agent_migration=queued["request"]["configuration"]["minecraft_serverpack_migration"]
            return jobs,queued

        def actual_agent_completion(fixture,state,pending,*,fingerprint=None):
            self.assertIsNotNone(self.agent_migration)
            # Host filesystem effects stay in the isolated unittest temp tree.
            root=Path(fixture.temp.name)/"joined-agent"
            runtime=root/"storage/runtime"
            stage=root/"storage/runtime.migration-stage"
            previous=root/"storage/runtime.migration-rollback"
            state_root=root/"agent-state"
            runtime.mkdir(parents=True)
            stage.mkdir(parents=True)
            (runtime/"world").mkdir()
            (runtime/"world/original-marker.txt").write_text("PRIVATE_WORLD_013")
            (runtime/"config").mkdir()
            (runtime/"config/customer.toml").write_text("CUSTOM_SETTING_PRESERVED")
            (runtime/"loader.txt").write_text("26.1.2.109")
            (runtime/"mods").mkdir()
            (stage/"world").mkdir()
            (stage/"world/original-marker.txt").write_text("PRIVATE_WORLD_013")
            (stage/"config").mkdir()
            (stage/"config/customer.toml").write_text("CUSTOM_SETTING_PRESERVED")
            (stage/"loader.txt").write_text(pending["bundle"]["loader_version"])
            (stage/"mods").mkdir()
            for child in pending["children"]:
                (stage/"mods"/(child["content_id"]+".jar")).write_bytes(
                    b"offline-simulated-jar-"+child["content_id"].encode())
            self.assertEqual(len(list((stage/"mods").glob("*.jar"))),291)
            archive=root/"retained-preupdate.tar.gz"
            with tarfile.open(archive,"w:gz") as tar:
                for relative in ("world/original-marker.txt","config/customer.toml"):
                    tar.add(runtime/relative,arcname=relative)
            h=hashlib.sha256(archive.read_bytes()).hexdigest()
            backup={"backup_id":"disposable-pre-013","sha256":h,
                    "size_bytes":archive.stat().st_size,"integrity_verified":True}
            migration=self.agent_migration
            journal={"phase":"committed","migration_plan_sha256":migration["migration_plan_sha256"],
                     "target_loader_version":migration["target_loader_version"]}
            def swap(*_):
                os.rename(runtime,previous)
                os.rename(stage,runtime)
            def ready(*_):
                return (runtime/"loader.txt").read_text()==migration["target_loader_version"] and (
                    runtime/"world/original-marker.txt").read_text()=="PRIVATE_WORLD_013" and (
                    runtime/"config/customer.toml").read_text()=="CUSTOM_SETTING_PRESERVED" and (
                    len(list((runtime/"mods").glob("*.jar")))==291)
            def finalize(*_):
                assert previous.is_dir()
                return {"status":"archived","observed_state":"stopped"}
            hooks={
                "revalidate":lambda e:{"valid":True,"install_allowed":False,
                    "migration_plan_sha256":e["migration_plan_sha256"]},
                "capacity":lambda e:{"sufficient":True,"install_allowed":False,
                    "requires_exclusive_recheck":True},
                "stop":lambda *_:None,
                "backup":lambda *_:backup,
                "stage":lambda *_:None,
                "swap":swap,
                "readiness":ready,
                "commit":lambda *_:{"status":"committed","journal":journal},
                "finalize":finalize,
                "rollback":lambda *_:self.fail("unexpected Agent rollback"),
            }
            with patch.object(instance_runtime,"STATE_DIR",state_root):
                detail=execute_minecraft_serverpack_migration(
                    {"agent_id":"pr839-isolated-agent"},pending["instance_id"],migration,hooks)
            self.assertEqual(detail["status"],"completed")
            self.assertEqual(detail["commit"]["journal"]["phase"],"committed")
            physical=attest_serverpack_mods(runtime,instance_id=pending["instance_id"],
                content_id=pending["content_id"],bundle=pending["bundle"])
            self.assertEqual(physical["mod_count"],291)
            detail["physical_manifest"]=physical
            self.assertEqual((runtime/"world/original-marker.txt").read_text(),"PRIVATE_WORLD_013")
            self.assertEqual((runtime/"config/customer.toml").read_text(),"CUSTOM_SETTING_PRESERVED")
            self.assertEqual((previous/"loader.txt").read_text(),"26.1.2.109")
            self.physical_transaction=detail
            return {"provisioning_id":state["provisioning_id"],
                    "instance_id":pending["instance_id"],
                    "status":"completed","progress":100,"current_step":"completed",
                    "minecraft_serverpack_migration":detail}

        with patch.object(scale_fixture,"bundle",mapped_bundle), \
             patch.object(scale_fixture,"child",mapped_child), \
             patch.object(scale_fixture,"local_artifact",mapped_artifact), \
             patch.object(atomic_fixture.AtomicPendingPublicationTest,"enqueue",client_enqueue), \
             patch.object(atomic_fixture.AtomicPendingPublicationTest,"completed",actual_agent_completion):
            super().setUp()
        self._promote_managed_sources_and_agent_states()

    def _promote_managed_sources_and_agent_states(self):
        """Really promote 291 hashed JARs and 493 Agent states with Controller CAS."""
        runtime=Path(self.fixture.temp.name)/"joined-agent/storage/runtime"
        candidate=self.pending["candidate_sha256"]
        def receipt():
            return confirmed_serverpack_receipt(
                backend=self.backend,provisioning_id=self.op["provisioning_id"],
                agent_id=self.agent,instance_id=self.iid,candidate_sha256=candidate)
        self.assertEqual(receipt()["bundle_revision"],3)

        source_parent=runtime/"content/modpacks/atm11"
        source_children=runtime/"content/mods"
        (source_parent/"mods").mkdir(parents=True)
        source_children.mkdir(parents=True)
        shared=["mod-a"]+[f"common-{i:03d}" for i in range(80)]
        oldids=shared+[f"legacy-{i:03d}" for i in range(201)]
        self.assertEqual(len(oldids),282)
        for cid in oldids:
            (source_parent/"mods"/(cid+".jar")).write_bytes(b"old-"+cid.encode())
            child_dir=source_children/cid
            child_dir.mkdir()
            (child_dir/(cid+".jar")).write_bytes(b"old-"+cid.encode())
        prepared=self.root/"prepared-source"
        (prepared/"parent/mods").mkdir(parents=True)
        (prepared/"children").mkdir()
        records=[]
        for child in self.pending["children"]:
            cid=child["content_id"]
            artifact=child["artifact"]
            filename=artifact["filename"]
            src=runtime/"mods"/filename
            self.assertTrue(src.is_file())
            digest=hashlib.sha256(src.read_bytes()).hexdigest()
            self.assertEqual(artifact["sha256"],digest)
            dest=prepared/"parent/mods"/filename
            shutil.copy2(src,dest)
            child_dest=prepared/"children"/cid
            child_dest.mkdir()
            shutil.copy2(src,child_dest/filename)
            records.append({"content_id":cid,"filename":filename,
                            "size_bytes":src.stat().st_size,"sha256":digest})
        self.assertEqual(len(records),291)
        (prepared/"verified-source-manifest.json").write_text(json.dumps({
            "kind":"VerifiedServerPackContentSources",
            "schema_version":1,"instance_id":self.iid,
            "candidate_sha256":candidate,
            "migration_plan_sha256":self.pending["migration_plan_sha256"],
            "loader_version":self.pending["bundle"]["loader_version"],
            "child_count":291,"files":records,
        },sort_keys=True))
        recovery=self.root/"source-recovery"
        recovery.mkdir()
        committed=promote_verified_sources(
            prepared=prepared,parent_live=source_parent,children_live=source_children,
            recovery=recovery,instance_id=self.iid,candidate_sha256=candidate,
            revision=3,controller_state=lambda:(receipt()["bundle_revision"],receipt()["candidate_sha256"]))
        self.assertEqual(committed["status"],"committed")
        self.assertEqual(len(list((source_parent/"mods").glob("*.jar"))),291)
        self.assertEqual(len(list((recovery/"previous-parent/mods").glob("*.jar"))),282)
        self.assertEqual(len([x for x in (recovery/"previous-children").iterdir() if x.is_dir()]),282)

        # Stage 493 local records, then actually perform journaled activation.
        active_states=self.paths["active_states"]
        active_snapshot=self.paths["active_snapshot"]
        staged_states=self.root/"prepared-agent-states"
        staged_snapshot=self.root/"prepared-activation.json"
        active_states.rename(staged_states)
        active_snapshot.rename(staged_snapshot)
        active_states.mkdir()
        (active_states/"previous.json").write_text('{"old":true}')
        active_snapshot.write_text('{"old":true}')
        active_ids=set()
        entries=[]
        all_ids=set()
        for file in staged_states.glob("*.json"):
            state=json.loads(file.read_text())
            cid=state["content_id"]
            all_ids.add(cid)
            if state["desired_state"]=="installed":
                active_ids.add(cid)
                managed_path=source_parent if cid=="atm11" else source_children/cid
                state["managed_path"]=str(managed_path)
                entries.append({"content_id":cid,"managed_path":str(managed_path)})
            else:
                state.pop("managed_path",None)
            file.write_text(json.dumps(state,sort_keys=True))
        self.assertEqual((len(all_ids),len(active_ids)),(493,292))
        snapshot={"kind":"CapivaraContentActivationSnapshot",
                  "schema_version":1,"instance_id":self.iid,
                  "entries":sorted(entries,key=lambda x:x["content_id"])}
        snapshot["checksum"]=hashlib.sha256(json.dumps(snapshot,sort_keys=True,
            separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        staged_snapshot.write_text(json.dumps(snapshot,sort_keys=True))
        manifest=json.loads(self.paths["staged_manifest"].read_text())
        manifest["activation_checksum"]=snapshot["checksum"]
        self.paths["staged_manifest"].write_text(json.dumps(manifest,sort_keys=True))
        state_recovery=self.root/"state-recovery"
        state_recovery.mkdir()
        state_done=promote_local_state_snapshot(
            staged_states=staged_states,staged_snapshot=staged_snapshot,
            active_states=active_states,active_snapshot=active_snapshot,
            recovery_dir=state_recovery,instance_id=self.iid,
            candidate_sha256=candidate,revision=3,
            expected_content_ids=all_ids,expected_active_ids=active_ids,
            controller_receipt=receipt)
        self.assertEqual(state_done["status"],"committed")
        self.assertEqual(len(list(active_states.glob("*.json"))),493)
        self.assertTrue((state_recovery/"previous-states/previous.json").exists())
        # The outbox references the same paths. Replace fixture evidence with
        # committed journals from the actual source/state swaps.
        shutil.copy2(recovery/"promotion.json",self.paths["source_promotion_journal"])
        shutil.copy2(state_recovery/"local-state-promotion.json",
                     self.paths["state_promotion_journal"])
        self.queued=read_serverpack_report_delivery(self.root)
        self.assertIsNotNone(self.queued)
        self.assertEqual(len(self.queued[0]["reports"]),493)
        self.runtime=runtime
        self.physical_source_promoted=True
        self.local_state_promoted=True

    def test_one_action_to_physical_swap_controller_cas_authenticated_ack(self):
        self.assertEqual(self.client_count,1)
        self.assertFalse(self.accepted["homologation_only"])
        self.assertTrue(self.accepted["production_authorized"])
        self.assertEqual(self.accepted["execution_mode"],"production")
        self.assertEqual(self.fixture.content.bundle_history(self.iid,"atm11")[0]["revision"],3)
        self.assertEqual(self.physical_transaction["status"],"completed")
        self.assertEqual(len(self.queued[0]["reports"]),493)
        # Reuse the tested real-authenticated HTTP flow, including lost ACK and replay.
        super().test_authentic_credentials_493_atomic_and_ack_lost_response_replay()
        self.assertEqual(self.count(),493)
        self.assertIsNone(read_serverpack_report_delivery(self.root))
        self.assertEqual(self.fixture.content.bundle_history(self.iid,"atm11")[0]["revision"],3)
        convergence_args=dict(
            backend=self.backend,provisioning_id=self.op["provisioning_id"],
            agent_id=self.agent,instance_id=self.iid,
            candidate_sha256=self.pending["candidate_sha256"],
            managed_content_dir=self.paths["active_states"],
            activation_snapshot_path=self.paths["active_snapshot"],
            runtime_dir=self.runtime)
        result=verify_serverpack_content_convergence(**convergence_args)
        self.assertEqual(result["status"],"ready")
        self.assertEqual((result["mods_verified"],result["installed_content"],
            result["removed_content"]),(291,292,201))
        child=self.pending["children"][0]
        file=self.runtime/"content/mods"/child["content_id"]/child["artifact"]["filename"]
        original=file.read_bytes()
        file.write_bytes(b"tampered")
        with self.assertRaises(ServerPackConvergenceError):
            verify_serverpack_content_convergence(**convergence_args)
        file.write_bytes(original)
        self.assertEqual(verify_serverpack_content_convergence(**convergence_args)["status"],"ready")
        print("ONE_CUSTOMER_ACTION_TO_ACK_PASS",json.dumps({
            "single_http_customer_action":True,
            "loader_transition":"26.1.2.109->26.1.2.126",
            "controller_queue_revision_before_agent":2,
            "controller_revision_after_agent":3,
            "physical_swap":True,"retained_old_world":True,
            "private_config_preserved":True,
            "client_actions":self.client_count,
            "agent_report_count":493,"agent_ack_retired":True,
            "jvm_readiness":"simulated",
            "agent_source_promotion":"real_journaled_291_mod_files",
            "agent_local_state_promotion":"real_journaled_493_states",
            "controller_convergence":"ready",
            "tampered_managed_source_blocks_health":True,
            "production_policy":"explicitly_allowlisted_isolated_identity",
            "agent_291_physical_sha_attestation":True,
            "production_touched":False,
        },sort_keys=True),flush=True)

if __name__=="__main__":
    import unittest
    unittest.main(defaultTest="SingleCustomerActionToAuthenticatedAckE2E",verbosity=2)
