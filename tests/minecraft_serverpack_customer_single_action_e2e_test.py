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
import re
import stat
import subprocess
import time
import zipfile
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
from minecraft_serverpack_migration_transaction import (execute_minecraft_serverpack_migration,
    MinecraftServerPackMigrationExecutionError)
from minecraft_serverpack_report_outbox import read_serverpack_report_delivery
from minecraft_serverpack_content_promotion import promote_verified_sources
from minecraft_serverpack_local_state_promotion import promote_local_state_snapshot
from minecraft_serverpack_content_receipt import confirmed_serverpack_receipt
from minecraft_serverpack_content_convergence import (
    verify_serverpack_content_convergence, ServerPackConvergenceError)


OFFICIAL_PACK_SHA256="b8635562de0931eb5cadb51954c0fb78658033928ef54b5f73be6cae5c8897fa"
OFFICIAL_PREVIOUS_SHA256="78cbca8ffd26fef6d5bef27dcf44fb53cf118c20d9da6a19d9af7911b6d8768e"


class SingleCustomerActionToAuthenticatedAckE2E(LargeRealCredentialHTTP):
    """Real customer route, Agent transaction and authenticated heartbeat joined."""

    def setUp(self):
        self.client_count=0
        self.physical_transaction=None
        self.accepted=None
        self.real_pack_root=getattr(self,"official_pack_root",None)
        if self.real_pack_root is not None:
            assert os.environ.get("GITHUB_ACTIONS")=="true", "official integration only on GitHub Actions"
            assert os.environ.get("RUNNER_ENVIRONMENT")=="github-hosted", "requires disposable runner"
            self.real_pack_root=Path(self.real_pack_root).resolve()
            source_zip=self.real_pack_root/"ServerFiles-0.14.0-beta.zip"
            assert source_zip.is_file()
            with source_zip.open("rb") as stream:
                assert hashlib.file_digest(stream,"sha256").hexdigest()==OFFICIAL_PACK_SHA256
            self.official_files=sorted((self.real_pack_root/"mods").glob("*.jar"))
            assert len(self.official_files)==291
            assert len({x.name for x in self.official_files})==291
            assert (self.real_pack_root/"libraries/net/neoforged/neoforge/26.1.2.126/unix_args.txt").is_file()
            with zipfile.ZipFile(source_zip) as archive:
                infos={i.filename:i for i in archive.infolist() if i.filename.startswith("mods/") and i.filename.endswith(".jar")}
                assert len(infos)==291
                assert all("mods/"+x.name in infos and infos["mods/"+x.name].file_size==x.stat().st_size for x in self.official_files)
            self.official_zip_size=source_zip.stat().st_size
            self.official_zip_sha=OFFICIAL_PACK_SHA256
            self.official_previous_zip=self.real_pack_root/"ServerFiles-0.13.0-beta.zip"
            assert self.official_previous_zip.is_file(), "missing official ATM11 0.13 ZIP"
            with self.official_previous_zip.open("rb") as stream:
                assert hashlib.file_digest(stream,"sha256").hexdigest()==OFFICIAL_PREVIOUS_SHA256
            with zipfile.ZipFile(self.official_previous_zip) as archive:
                assert archive.testzip() is None
                old_names=[i.filename for i in archive.infolist()
                    if i.filename.startswith("mods/") and i.filename.endswith(".jar")]
                assert len(old_names)==282 and len(set(old_names))==282
                assert "neoforge-26.1.2.124-installer.jar" in archive.namelist()
                self.official_previous_mods=sorted(old_names)
            self.official_previous_hashes={}
        else:
            self.official_previous_mods=None
            self.official_files=None
            self.official_zip_size=823456
            self.official_zip_sha="d"*64
        def actual_loader(value):
            return {"26.1.2.94":"26.1.2.124","26.1.2.109":"26.1.2.126"}.get(value,value)
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
            # Bind the frozen pending candidate to the official ZIP filenames/hashes
            # on the opt-in CI path, or deterministic tiny fixtures in normal tests.
            member_index={m["content_id"]:m for m in pending["bundle"]["members"]}
            for number,item in enumerate(pending["children"]):
                cid=item["content_id"]
                if self.official_files is not None:
                    file=self.official_files[number]
                    with file.open("rb") as stream:
                        digest=hashlib.file_digest(stream,"sha256").hexdigest()
                    filename=file.name
                    size=file.stat().st_size
                else:
                    raw=b"offline-simulated-jar-"+cid.encode()
                    digest=hashlib.sha256(raw).hexdigest()
                    filename=cid+".jar"
                    size=len(raw)
                item["artifact"]["sha256"]=digest
                item["artifact"]["size_bytes"]=size
                item["artifact"]["filename"]=filename
                if self.official_files is not None:
                    item["artifact"]["bundle_member"]="mods/"+filename
                    member_index[cid]["path"]="mods/"+filename
                member_index[cid]["artifact"]=dict(item["artifact"])
            rebound=build_pending_bundle_commit(**{key:pending[key] for key in (
                "instance_id","content_id","transfer_id",
                "migration_plan_sha256","expected_previous_revision",
                "parent","bundle","children","requested_by")})
            pending.clear()
            pending.update(rebound)
            aid="pr839-isolated-agent"
            target=pending["bundle"]["loader_version"]
            old="26.1.2.124"
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
                    "incoming_sha256":self.official_zip_sha,
                    "filename":"ServerFiles-0.14.0-beta.zip",
                    "archive_size_bytes":self.official_zip_size,
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
            (runtime/"loader.txt").write_text("26.1.2.124")
            (runtime/"mods").mkdir()
            if self.real_pack_root is not None:
                self._stage_official_previous_runtime(runtime)
                # Customer data is never sourced from a modpack ZIP.
                (runtime/"world/original-marker.txt").write_text("PRIVATE_WORLD_013")
                (runtime/"config/customer.toml").write_text("CUSTOM_SETTING_PRESERVED")
                assert len(list((runtime/"mods").glob("*.jar")))==282
            (stage/"world").mkdir()
            (stage/"world/original-marker.txt").write_text("PRIVATE_WORLD_013")
            (stage/"config").mkdir()
            (stage/"config/customer.toml").write_text("CUSTOM_SETTING_PRESERVED")
            (stage/"loader.txt").write_text(pending["bundle"]["loader_version"])
            (stage/"mods").mkdir()
            if self.real_pack_root is None:
                for child in pending["children"]:
                    (stage/"mods"/(child["content_id"]+".jar")).write_bytes(
                        b"offline-simulated-jar-"+child["content_id"].encode())
                self.assertEqual(len(list((stage/"mods").glob("*.jar"))),291)
            def prepare_files(*_):
                if self.real_pack_root is None:
                    return
                for name in ("libraries","config","kubegroovy","local"):
                    source=self.real_pack_root/name
                    if source.is_dir():
                        shutil.copytree(source,stage/name,dirs_exist_ok=True)
                for child in pending["children"]:
                    name=child["artifact"]["filename"]
                    source=self.real_pack_root/"mods"/name
                    target=stage/"mods"/name
                    shutil.copy2(source,target)
                    with target.open("rb") as stream:
                        assert hashlib.file_digest(stream,"sha256").hexdigest()==child["artifact"]["sha256"]
                (stage/"eula.txt").write_text("eula=true\n")
                (stage/"server.properties").write_text(
                    "server-ip=127.0.0.1\nserver-port=25596\nonline-mode=false\n"
                    "max-players=1\nview-distance=2\nsimulation-distance=2\n"
                    "enable-query=false\nenable-rcon=false\n")
                self.assertEqual(len(list((stage/"mods").glob("*.jar"))),291)
                assert (stage/"libraries/net/neoforged/neoforge/26.1.2.126/unix_args.txt").is_file()
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
                files_ready=(runtime/"loader.txt").read_text()==migration["target_loader_version"] and (
                    runtime/"world/original-marker.txt").read_text()=="PRIVATE_WORLD_013" and (
                    runtime/"config/customer.toml").read_text()=="CUSTOM_SETTING_PRESERVED" and (
                    len(list((runtime/"mods").glob("*.jar")))==291)
                if not files_ready:return False
                if self.real_pack_root is None:return True
                return self._boot_real_official_runtime(runtime)
            def rollback(*_):
                # If real boot fails, restore the old world, configs and runtime
                # under the migration lock (the failing test remains fail closed).
                if runtime.is_dir():
                    failed=root/"storage/runtime.migration-failed"
                    if failed.exists():raise RuntimeError("preexisting failed runtime")
                    os.rename(runtime,failed)
                if previous.is_dir():
                    os.rename(previous,runtime)
                assert (runtime/"world/original-marker.txt").read_text()=="PRIVATE_WORLD_013"
                assert (runtime/"config/customer.toml").read_text()=="CUSTOM_SETTING_PRESERVED"
                self.readiness_failure_rolled_back=True
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
                "stage":prepare_files,
                "swap":swap,
                "readiness":ready,
                "commit":lambda *_:{"status":"committed","journal":journal},
                "finalize":finalize,
                "rollback":rollback if self.real_pack_root is not None else (
                    lambda *_:self.fail("unexpected Agent rollback")),
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
            self.assertEqual((previous/"loader.txt").read_text(),"26.1.2.124")
            if self.real_pack_root is not None:
                self.assertEqual(len(list((previous/"mods").glob("*.jar"))),282)
                for name,digest in self.official_previous_hashes.items():
                    with (previous/"mods"/name).open("rb") as stream:
                        self.assertEqual(hashlib.file_digest(stream,"sha256").hexdigest(),digest)
            if self.real_pack_root is not None:
                self.assertTrue(self.real_boot_result["pass"])
                detail["real_boot"]=dict(self.real_boot_result)
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


    def _stage_official_previous_runtime(self,runtime):
        """Read-only source ZIP; extract official 0.13 files only to disposable runtime."""
        assert self.real_pack_root is not None
        assert self.official_previous_zip.is_file()
        with zipfile.ZipFile(self.official_previous_zip) as archive:
            for info in archive.infolist():
                parts=Path(info.filename).parts
                if not parts or parts[0] not in ("mods","config","kubegroovy","local"):
                    continue
                assert ".." not in parts and not info.filename.startswith("/")
                assert "\\" not in info.filename
                assert not stat.S_ISLNK(info.external_attr >> 16)
                dest=runtime.joinpath(*parts)
                assert dest.resolve().is_relative_to(runtime.resolve())
                if info.is_dir():
                    dest.mkdir(parents=True,exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(info) as source,dest.open("wb") as output:
                    shutil.copyfileobj(source,output,1024*1024)
        old_mods=list((runtime/"mods").glob("*.jar"))
        assert len(old_mods)==282
        assert {p.name for p in old_mods} == {Path(x).name for x in self.official_previous_mods}
        self.official_previous_hashes={}
        for path in old_mods:
            with path.open("rb") as stream:
                self.official_previous_hashes[path.name]=hashlib.file_digest(stream,"sha256").hexdigest()
        assert len(self.official_previous_hashes)==282
        print("DSM1013_OFFICIAL_013_READY",
              json.dumps({"files":282,"loader":"26.1.2.124",
                 "zip_sha256":OFFICIAL_PREVIOUS_SHA256}),flush=True)

    def _prove_readiness_rollback_with_official_013(self):
        """Inject a failure after swapping *real* 0.14 mods over *real* 0.13 mods.

        Reuses the already-verified disposable runtime and preserved previous
        tree. Does NOT restart the JVM or touch the Controller in this failure
        rehearsal. Validates automatic compensation before lock release.
        """
        assert self.real_pack_root is not None
        base=Path(self.fixture.temp.name)/"joined-agent/storage"
        live=self.runtime
        previous=base/"runtime.migration-rollback"
        staged=base/"official-readiness-failure-stage"
        testroot=base/"official-readiness-failure-root"
        testroot.mkdir()
        active=testroot/"live"
        backup=testroot/"before-swap"
        aborted=testroot/"aborted-new"
        assert live.is_dir() and previous.is_dir()
        assert not any(p.exists() for p in (staged,active,backup,aborted))
        # Both are in the same disposable fixture; move rather than copy 1+ GiB.
        os.rename(live,staged)
        os.rename(previous,active)
        assert len(list((active/"mods").glob("*.jar")))==282
        assert len(list((staged/"mods").glob("*.jar")))==291
        original_sha=self.official_previous_hashes.copy()
        for name,digest in original_sha.items():
            with (active/"mods"/name).open("rb") as stream:
                self.assertEqual(hashlib.file_digest(stream,"sha256").hexdigest(),digest)
        events=[]
        archive=testroot/"before-update.tar.gz"
        with tarfile.open(archive,"w:gz") as tar:
            for item in ("world/original-marker.txt","config/customer.toml"):
                tar.add(active/item,arcname=item)
        with archive.open("rb") as f:
            archive_sha=hashlib.file_digest(f,"sha256").hexdigest()
        backup_receipt={"backup_id":"official-013-failure-injection",
             "sha256":archive_sha,"size_bytes":archive.stat().st_size,
             "integrity_verified":True}
        def swap(*_):
            events.append("swap")
            os.rename(active,backup)
            os.rename(staged,active)
        def readiness(*_):
            events.append("readiness_injected_false")
            assert len(list((active/"mods").glob("*.jar")))==291
            return False
        def commit(*_):
            raise AssertionError("Controller commit must not run after readiness failure")
        def rollback(*_):
            events.append("rollback")
            assert backup.is_dir()
            os.rename(active,aborted)
            os.rename(backup,active)
            assert len(list((active/"mods").glob("*.jar")))==282
        hooks={
            "revalidate":lambda e:{"valid":True,"install_allowed":False,
                "migration_plan_sha256":e["migration_plan_sha256"]},
            "capacity":lambda e:{"sufficient":True,"install_allowed":False,
                "requires_exclusive_recheck":True},
            "stop":lambda *_:events.append("stop"),
            "backup":lambda *_:dict(backup_receipt),
            "stage":lambda *_:events.append("stage"),
            "swap":swap,
            "readiness":readiness,
            "commit":commit,
            "rollback":rollback,
        }
        with patch.object(instance_runtime,"STATE_DIR",self.root/"isolated-failure-lock"):
            with self.assertRaises(MinecraftServerPackMigrationExecutionError) as caught:
                execute_minecraft_serverpack_migration(
                    {"agent_id":self.agent},self.iid,self.agent_migration,hooks)
        self.assertIn("rolled_back",caught.exception.trace)
        self.assertNotIn("committed",caught.exception.trace)
        self.assertEqual(events,["stop","stage","swap","readiness_injected_false","rollback"])
        self.assertTrue((active/"world/original-marker.txt").read_text()=="PRIVATE_WORLD_013")
        self.assertTrue((active/"config/customer.toml").read_text()=="CUSTOM_SETTING_PRESERVED")
        self.assertEqual((active/"loader.txt").read_text(),"26.1.2.124")
        self.assertEqual((aborted/"loader.txt").read_text(),"26.1.2.126")
        for name,digest in original_sha.items():
            with (active/"mods"/name).open("rb") as stream:
                self.assertEqual(hashlib.file_digest(stream,"sha256").hexdigest(),digest)
        self.assertEqual(self.fixture.content.bundle_history(self.iid,"atm11")[0]["revision"],3)
        self.assertEqual(self.count(),493)
        self.assertIsNone(read_serverpack_report_delivery(self.root))
        self.failure_rollback_verified=True
        print("DSM1013_OFFICIAL_ROLLBACK_PASS",json.dumps({
            "old_mods":282,"new_mods":291,
            "old_loader":"26.1.2.124","target_loader":"26.1.2.126",
            "world_restored":True,"config_restored":True,
            "all_old_hashes_restored":True,"agent_rollback_before_unlock":True,
            "controller_revision_unchanged":3,"agent_states_unchanged":493,
            "injected_failure":"readiness_false_after_physical_swap",
            "jvm_boot_for_failure_injection":"not_started",
            "production_touched":False,
        },sort_keys=True),flush=True)

    def _boot_real_official_runtime(self,runtime):
        """One actual JVM startup under the same Agent migration operation fence.

        No real customer server is touched. The official runner supplies
        NeoForge libraries + 291 official JARs; temp world/port are isolated.
        The Agent can commit only if Done, level.dat and clean stop all pass.
        """
        root=self.real_pack_root
        assert root is not None
        report_file=root/"joined-one-action-boot.json"
        log_file=root/"joined-one-action-boot.log"
        if report_file.exists() or log_file.exists():
            raise RuntimeError("stale boot evidence; refuse overwriting")
        command=["java","-Xms1024M","-Xmx5120M","-Djava.awt.headless=true",
            "@libraries/net/neoforged/neoforge/26.1.2.126/unix_args.txt","nogui"]
        result={"kind":"ATM11JoinedSingleActionOfficialBoot","version":"0.14.0-beta",
                "loader":"26.1.2.126","mods":291,"done":False,
                "world":False,"stopped":False,"pass":False}
        proc=None
        started=time.monotonic()
        try:
            with log_file.open("w",encoding="utf-8") as out:
                env={**os.environ,"HOME":str(runtime),"TMPDIR":str(runtime)}
                env.pop("JAVA_TOOL_OPTIONS",None)
                proc=subprocess.Popen(command,cwd=runtime,stdin=subprocess.PIPE,
                    stdout=out,stderr=subprocess.STDOUT,text=True,env=env)
                print("DSM1013_JOINED_OFFICIAL_JVM_STARTED",flush=True)
                while time.monotonic()-started<720:
                    time.sleep(3)
                    if re.search(r"Done \([0-9.]+s\)!",log_file.read_text(errors="replace")):
                        result["done"]=True
                        break
                    if proc.poll() is not None:break
                if proc.poll() is None:
                    if result["done"]:time.sleep(4)
                    try:
                        proc.stdin.write("stop\n");proc.stdin.flush()
                        proc.wait(timeout=75)
                        result["stopped"]=proc.returncode==0
                    except (BrokenPipeError,subprocess.TimeoutExpired):
                        proc.terminate()
                        try:proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill();proc.wait(timeout=10)
                result["exit_code"]=proc.returncode
            level=runtime/"world/level.dat"
            result["world"]=level.is_file() and level.stat().st_size>0
        except Exception as exc:
            result["exception"]=repr(exc)
        finally:
            if proc and proc.poll() is None:
                proc.kill();proc.wait(timeout=10)
            result["duration_seconds"]=round(time.monotonic()-started,2)
            result["pass"]=bool(result["done"] and result["world"]
                                  and result["stopped"] and result.get("exit_code")==0)
            lines=log_file.read_text(errors="replace").splitlines() if log_file.exists() else []
            result["log_tail"]=lines[-40:]
            report_file.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
            self.real_boot_result={k:v for k,v in result.items() if k!="log_tail"}
            print("DSM1013_JOINED_OFFICIAL_BOOT_RESULT",
                json.dumps(self.real_boot_result,sort_keys=True),flush=True)
        return bool(result["pass"])

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
        if self.real_pack_root is not None:
            old_path=Path(self.fixture.temp.name)/"joined-agent/storage/runtime.migration-rollback/mods"
            actual_old=sorted(old_path.glob("*.jar"))
            self.assertEqual(len(actual_old),282)
        else:
            actual_old=[]
        for index,cid in enumerate(oldids):
            child_dir=source_children/cid
            child_dir.mkdir()
            if self.real_pack_root is not None:
                file=actual_old[index]
                shutil.copy2(file,source_parent/"mods"/file.name)
                shutil.copy2(file,child_dir/file.name)
            else:
                (source_parent/"mods"/(cid+".jar")).write_bytes(b"old-"+cid.encode())
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
        if self.real_pack_root is not None:
            self.assertEqual({p.name for p in (recovery/"previous-parent/mods").glob("*.jar")},
                set(self.official_previous_hashes))

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
        if self.real_pack_root is not None:
            self._prove_readiness_rollback_with_official_013()
        print("ONE_CUSTOMER_ACTION_TO_ACK_PASS",json.dumps({
            "single_http_customer_action":True,
            "loader_transition":"26.1.2.124->26.1.2.126",
            "controller_queue_revision_before_agent":2,
            "controller_revision_after_agent":3,
            "physical_swap":True,"retained_old_world":True,
            "private_config_preserved":True,
            "client_actions":self.client_count,
            "agent_report_count":493,"agent_ack_retired":True,
            "jvm_readiness":"real_official_done_and_clean_stop" if self.real_pack_root is not None else "simulated",
            "official_zip_verified":self.real_pack_root is not None,
            "previous_013_runtime":"official_282_mods_and_configs_with_disposable_world"
                if self.real_pack_root is not None else "disposable_synthetic_fixture",
            "readiness_failure_rollback_verified":getattr(self,"failure_rollback_verified",False),
            "customer_preview":"controlled_isolated_fixture",
            "agent_source_promotion":"real_journaled_291_mod_files",
            "agent_local_state_promotion":"real_journaled_493_states",
            "controller_convergence":"ready",
            "tampered_managed_source_blocks_health":True,
            "production_policy":"explicitly_allowlisted_isolated_identity",
            "agent_291_physical_sha_attestation":True,
            "production_touched":False,
        },sort_keys=True),flush=True)

# Never run the 291-mod real JVM on an installed DSM host.
class OfficialATM11SingleActionBootE2E(SingleCustomerActionToAuthenticatedAckE2E):
    def setUp(self):
        if (os.environ.get("CAPIVARA_RUN_OFFICIAL_ATM11_JOINED_E2E")!="1"
                or os.environ.get("GITHUB_ACTIONS")!="true"
                or os.environ.get("RUNNER_ENVIRONMENT")!="github-hosted"):
            self.skipTest("official ATM11 joined E2E requires opt-in disposable runner")
        name=os.environ.get("DSM_1013_OFFICIAL_PACK_ROOT")
        if not name:raise RuntimeError("missing official Server Pack directory")
        self.official_pack_root=Path(name)
        super().setUp()


if __name__=="__main__":
    import unittest
    unittest.main(defaultTest="SingleCustomerActionToAuthenticatedAckE2E",verbosity=2)
