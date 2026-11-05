"""Explicit opt-in full Minecraft NeoForge live, root helper, worker E2E.

Requires host root, systemd, source-only installed NeoForge libraries and 3GB
memory. Only /tmp and one named /run/systemd/system unit are mutated.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tests.minecraft_serverpack_finalization_subprocess_e2e_test import (
    IID, AID, PLAN, ROOT, WORKER
)
from tests import minecraft_serverpack_privileged_root_test as helper_test

RUNTIME=ROOT/"agents/linux/runtime"
DONOR=Path("/opt/dsm/runtime/hybrid-instance-storage/cli-000001-minecraft-003/runtime")
LOADER="26.1.2.109"
UNIT=f"capivara-instance-{IID}.service"

@unittest.skipUnless(
    os.environ.get("CAPIVARA_RUN_REAL_NEOFORGE_MIGRATION_E2E")=="1"
    and hasattr(os,"geteuid") and os.geteuid()==0,
    "real NeoForge E2E must be expressly opted into on disposable Linux host",
)
class FullLiveNeoForgeIntegrationE2E(unittest.TestCase):
    def setUp(self):
        if not (DONOR/"libraries/net/neoforged/neoforge"/LOADER/"unix_args.txt").is_file():
            self.skipTest("required NeoForge libraries are not available read-only")
        self.unit_file=Path("/run/systemd/system")/UNIT
        if self.unit_file.exists():
            raise RuntimeError("refusing to overwrite existing unit")
        self.temp=tempfile.TemporaryDirectory(prefix="dsm-pr981-full-neoforge-")
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.base.chmod(0o755)
        self.unit_file.write_text(
            "[Unit]\nDescription=DSM PR981 opt-in real NeoForge isolated\n"
            "[Service]\nType=simple\nUser=capivara\nGroup=capivara\n"
            f"WorkingDirectory={self.base}/storage/{IID}/runtime\n"
            f"ExecStart=/bin/sh {self.base}/storage/{IID}/runtime/start.sh\n"
            "Restart=no\nTimeoutStopSec=12\nSuccessExitStatus=143\n"
            "MemoryMax=3G\nCPUQuota=160%\nTasksMax=180\n"
            "NoNewPrivileges=yes\nIPAddressDeny=any\nIPAddressAllow=localhost\n"
        )
        self.addCleanup(self.cleanup_unit)
        subprocess.run(["systemctl","daemon-reload"],check=True,timeout=15)
        self.state=self.base/"agent-state"
        self.storage=self.base/"storage"/IID
        self.old=self.storage/"runtime"
        self.stage=self.storage/"runtime.migration-stage"
        self.old.mkdir(parents=True)
        (self.old/"world").mkdir()
        (self.old/"world/original-marker.txt").write_text("PR981_ORIGINAL")
        self.stage.mkdir()
        shutil.copytree(DONOR/"libraries",self.stage/"libraries")
        canonical=self.stage/"libraries/net/neoforged/neoforge"/LOADER/"unix_args.txt"
        shutil.copyfile(canonical,self.stage/"capivara-launch.args")
        shutil.copyfile(DONOR/"eula.txt",self.stage/"eula.txt")
        (self.stage/"user_jvm_args.txt").write_text("-Xms512M -Xmx2G\n")
        (self.stage/"server.properties").write_text(
            "server-ip=127.0.0.1\nserver-port=25595\n"
            "enable-query=false\nenable-rcon=false\n"
            "max-players=1\nview-distance=2\nsimulation-distance=2\n"
            "online-mode=true\nmotd=DSM PR981 E2E\n")
        (self.stage/"start.sh").write_text(
            "#!/bin/sh\nexec /usr/lib/jvm/java-25-openjdk-amd64/bin/java "
            "-Xms512M -Xmx2048M @libraries/net/neoforged/neoforge/"
            +LOADER+"/unix_args.txt nogui\n")
        (self.stage/"start.sh").chmod(0o755)
        (self.stage/"world").mkdir()
        (self.stage/"world/original-marker.txt").write_text("PR981_ORIGINAL")
        (self.stage/"mods").mkdir()
        with zipfile.ZipFile(self.stage/"mods/pr981-empty-test.jar","w") as stub:
            stub.writestr("META-INF/MANIFEST.MF","Manifest-Version: 1.0\n")
        # The retained archive follows the same manifest policy as Agent backups.
        self.backup_id="pr981-live-backup"
        self.backup=self.state/"backups"/IID/(self.backup_id+".tar.gz")
        self.backup.parent.mkdir(parents=True)
        manifest={"kind":"CapivaraInstanceBackup","backup_format":"capivara-instance",
                  "backup_id":self.backup_id,"source_instance":IID}
        with tarfile.open(self.backup,"w:gz") as pack:
            data=json.dumps(manifest).encode()
            item=tarfile.TarInfo(".capivara-backup-manifest.json")
            item.size=len(data)
            pack.addfile(item,io.BytesIO(data))
            pack.add(self.old/"world/original-marker.txt",arcname="world/original-marker.txt")
        self.backup_evidence={
            "backup_id":self.backup_id,
            "sha256":hashlib.sha256(self.backup.read_bytes()).hexdigest(),
            "size_bytes":self.backup.stat().st_size,
            "integrity_verified":True,
        }
        self.agent_config=self.base/"agent.json"
        self.agent_config.write_text(json.dumps({"agent_id":AID}))
        self.record={"instance_id":IID,"agent_id":AID,"game_id":"minecraft",
                     "environment_id":"minecraft.java.neoforge","adapter":"systemd",
                     "instance_state_root":str(self.storage),
                     "working_directory":str(self.old)}
        for suffix in ("instances","instance-operations","instance-provisioning"):
            (self.state/suffix).mkdir(parents=True,exist_ok=True)
        (self.state/"instances"/(IID+".json")).write_text(json.dumps(self.record))
        self.op=self.state/"instance-operations"/(IID+".json")
        self.res=self.state/"instance-provisioning"/"pr981-live.result.json"
        self.env={
            **os.environ,"CAPIVARA_AGENT_STATE_DIR":str(self.state),
            "CAPIVARA_BACKUP_ROOT":str(self.state/"backups"),
            "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE":IID,
            "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"0",
            "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER":"1",
            "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER_ACK":"AUTHORIZED",
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"homologation",
        }
        helper_test.ServerPackMigrationRootTest.setUpClass()
        self.helper=helper_test.ServerPackMigrationRootTest.helper
        self.request_root=self.base/"privileged-requests"
        self.request_root.mkdir()
        self.spec=dict(self.record)
        self.user=pwd.getpwnam("capivara")
        self.adapter=None

    def cleanup_unit(self):
        subprocess.run(["systemctl","stop",UNIT],capture_output=True,timeout=20)
        self.unit_file.unlink(missing_ok=True)
        subprocess.run(["systemctl","daemon-reload"],capture_output=True,timeout=15)
        subprocess.run(["systemctl","reset-failed",UNIT],capture_output=True,timeout=15)

    def helper_phase(self,phase,**kwargs):
        payload={"kind":"CapivaraPrivilegedMaterializationRequest",
                 "schema_version":1,"action":"minecraft-serverpack-swap-phase",
                 "phase":phase,"agent_id":AID,"instance_id":IID,
                 "spec":self.spec,**kwargs}
        (self.request_root/(IID+".request.json")).write_text(json.dumps(payload))
        with patch.object(self.helper,"REQUEST_ROOT",self.request_root), \
             patch.object(self.helper,"CONFIG_PATH",self.agent_config), \
             patch.object(self.helper,"validate_runtime_spec",return_value=self.spec), \
             patch.object(self.helper,"resolve_materializer",return_value=object()), \
             patch.object(self.helper,"_instance_storage_root",return_value=self.storage.parent):
            return self.helper.run(IID)["operation"]

    def worker(self):
        return subprocess.run(
            [sys.executable,str(WORKER),str(self.agent_config),IID],
            env=self.env,capture_output=True,text=True,timeout=130)

    def test_privileged_swap_real_neoforge_archive_official_worker_restart(self):
        from adapters.systemd import SystemdAdapter
        from minecraft_serverpack_migration_provisioning import (
            _readiness_log_baseline,_wait_for_done
        )
        prepare=self.helper_phase("prepare",migration_plan_sha256=PLAN,
                                  target_loader_version=LOADER,backup=self.backup_evidence)
        self.assertEqual(prepare["phase"],"prepared")
        self.assertEqual(self.helper_phase("switch")["phase"],"swapped")
        subprocess.run(["chown","-R","capivara:capivara",str(self.storage)],check=True)
        self.adapter=SystemdAdapter()
        baseline=_readiness_log_baseline(self.old)
        self.adapter.start(self.record)
        self.assertTrue(_wait_for_done(self.record,self.adapter,timeout_seconds=90,baseline=baseline))
        self.adapter.stop(self.record)
        commit=self.helper_phase("commit",readiness_evidence={
            "passed":True,"migration_plan_sha256":PLAN,
            "target_loader_version":LOADER,"serverpack_mod_count":1})
        self.assertEqual(commit["status"],"committed")
        operation={"instance_id":IID,"agent_id":AID,"operation":"minecraft_serverpack_migration",
                   "status":"finalization_pending","migration_plan_sha256":PLAN}
        result={"instance_id":IID,"provisioning_id":"pr981-live","status":"running",
                "progress":99,"finalization_state":"pending",
                "current_step":"minecraft_serverpack_finalization",
                "minecraft_serverpack_migration":{
                    "status":"finalization_pending",
                    "trace":["committed","finalization_pending"],
                    "migration_plan_sha256":PLAN,
                    "target_loader_version":LOADER,
                    "commit":{"initial_active_state":"active"},
                    "backup":self.backup_evidence}}
        self.op.write_text(json.dumps(operation))
        self.res.write_text(json.dumps(result))
        archived=self.helper_phase("archive-committed")
        self.assertEqual(archived["status"],"archived")
        # The archived checkpoint survives the separate recovery process.
        replay=self.worker()
        self.assertEqual(replay.returncode,0,replay.stderr+replay.stdout)
        self.assertEqual(json.loads(self.op.read_text())["status"],"completed")
        self.assertEqual(json.loads(self.res.read_text())["status"],"completed")
        self.assertEqual(self.adapter.status(self.record)["active_state"],"active")
        self.assertEqual((self.old/"world/original-marker.txt").read_text(),"PR981_ORIGINAL")
        self.assertTrue((self.old/"world/level.dat").is_file())
        self.assertEqual(next((self.storage/".dsm/migration-history").glob(
            "*/runtime.migration-rollback/world/original-marker.txt")).read_text(),"PR981_ORIGINAL")
        again=self.worker()
        self.assertEqual(again.returncode,0,again.stderr+again.stdout)
        self.assertEqual(len(list((self.storage/".dsm/migration-history").iterdir())),1)

if __name__=="__main__":
    unittest.main()

