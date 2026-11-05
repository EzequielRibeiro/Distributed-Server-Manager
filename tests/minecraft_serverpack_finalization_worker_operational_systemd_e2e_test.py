"""Opt-in actual worker + retained backup + systemd activation E2E.

Runs only with explicit opt-in and root on an isolated Linux host. Actual
Minecraft boot has a separate live-server gate; this worker E2E uses a sleep
fixture which logs a fresh Done line under a unique disposable systemd unit.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest

from tests.minecraft_serverpack_finalization_subprocess_e2e_test import (
    AID, IID, PLAN, ROOT, FinalizationWorkerProcessE2E,
)

@unittest.skipUnless(
    os.environ.get("CAPIVARA_RUN_SYSTEMD_FINALIZATION_E2E") == "1"
    and hasattr(os,"geteuid") and os.geteuid()==0,
    "requires opt-in and root on isolated Linux systemd host",
)
class ActualOperationalWorkerSystemdE2E(unittest.TestCase):
    def setUp(self):
        fixture=FinalizationWorkerProcessE2E(
            methodName="test_worker_reconciles_real_files_then_is_idempotent")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f=fixture
        f=fixture
        sys.path.insert(0,str(ROOT/"agents/common"))
        from minecraft_serverpack_migration_swap import prepare,switch,commit,archive_committed
        shutil.rmtree(f.hist)
        original=f.storage/"runtime"
        (original/"world").mkdir()
        (original/"world/level.dat").write_bytes(b"PR981_OLD_WORLD")
        stage=f.storage/"runtime.migration-stage"
        canonical=stage/"libraries/net/neoforged/neoforge/26.1.2.109/unix_args.txt"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("--neoforge-build 26.1.2.109\n")
        (stage/"capivara-launch.args").write_bytes(canonical.read_bytes())
        (stage/"world").mkdir()
        (stage/"world/level.dat").write_bytes(b"PR981_NEW_WORLD")
        (stage/"logs").mkdir()
        backup_id="pr981-retained"
        archive=f.state/"backups"/IID/(backup_id+".tar.gz")
        archive.parent.mkdir(parents=True)
        manifest={
            "kind":"CapivaraInstanceBackup",
            "backup_format":"capivara-instance",
            "backup_id":backup_id,
            "source_instance":IID,
        }
        with tarfile.open(archive,"w:gz") as bundle:
            content=json.dumps(manifest).encode()
            meta=tarfile.TarInfo(".capivara-backup-manifest.json")
            meta.size=len(content)
            bundle.addfile(meta,io.BytesIO(content))
            payload=b"PR981_OLD_WORLD"
            meta=tarfile.TarInfo("world/level.dat")
            meta.size=len(payload)
            bundle.addfile(meta,io.BytesIO(payload))
        backup={
            "backup_id":backup_id,
            "sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
            "size_bytes":archive.stat().st_size,
            "integrity_verified":True,
        }
        prepare(f.storage,migration_plan_sha256=PLAN,
                target_loader_version="26.1.2.109",backup=backup)
        switch(f.storage)
        commit(f.storage,readiness_passed=True)
        archived=archive_committed(f.storage)
        assert archived["status"]=="archived"
        f.detail.update({
            "status":"finalization_pending",
            "trace":["committed","finalization_pending"],
            "commit":{"initial_active_state":"active"},
            "backup":backup,
        })
        f.result.update({
            "status":"running",
            "progress":99,
            "finalization_state":"pending",
            "current_step":"minecraft_serverpack_finalization",
        })
        f.provision.write_text(json.dumps(f.result))
        f.record["adapter"]="systemd"
        (f.state/"instances"/(IID+".json")).write_text(json.dumps(f.record))
        # Create a unique, disposable service that emits the same readiness
        # contract as a real NeoForge boot but does not consume game resources.
        self.unit="capivara-instance-"+IID+".service"
        self.unitfile=Path("/run/systemd/system")/self.unit
        if self.unitfile.exists():raise RuntimeError("test systemd unit already exists")
        log=original/"logs/latest.log"
        stub=f.root/"dummy_server.py"
        stub.write_text(
            "import pathlib,time\n"
            "p=pathlib.Path("+repr(str(log))+")\n"
            "with p.open('a') as fh:\n"
            " fh.write('[Server thread/INFO]: Done (0.2s)! For help, type help\\n')\n"
            " fh.flush()\n"
            "time.sleep(45)\n"
        )
        self.unitfile.write_text(
            "[Unit]\nDescription=DSM PR981 operational worker isolated fixture\n"
            "[Service]\nType=simple\nExecStart="+sys.executable+" "+str(stub)+"\n"
            "Restart=no\nTimeoutStopSec=3\n"
        )
        self.addCleanup(self.cleanup_unit)
        subprocess.run(["systemctl","daemon-reload"],check=True,timeout=15)
        self.env={
            **f.env,
            "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"0",
            "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER":"1",
            "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER_ACK":"AUTHORIZED",
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"homologation",
        }

    def cleanup_unit(self):
        subprocess.run(["systemctl","stop",self.unit],capture_output=True,timeout=15)
        self.unitfile.unlink(missing_ok=True)
        subprocess.run(["systemctl","daemon-reload"],capture_output=True,timeout=15)
        subprocess.run(["systemctl","reset-failed",self.unit],capture_output=True,timeout=15)

    def test_root_helper_archive_then_official_worker_restores(self):
        """Connect real root helper run() and actual worker on one isolated unit."""
        from unittest.mock import patch
        from tests import minecraft_serverpack_privileged_root_test as root_fixtures
        if not hasattr(root_fixtures.ServerPackMigrationRootTest,"helper"):
            root_fixtures.ServerPackMigrationRootTest.setUpClass()
        helper=root_fixtures.ServerPackMigrationRootTest.helper
        f=self.f
        archive_dir=next(f.hist.iterdir())
        # Rebuild the exact committed intermediate state before archiving:
        # journal and rollback have already been verified by setup.
        (archive_dir/"runtime.migration-rollback").rename(
            f.storage/"runtime.migration-rollback")
        (archive_dir/"minecraft-serverpack-migration.json").rename(
            f.storage/".dsm/minecraft-serverpack-migration.json")
        (f.storage/".dsm/minecraft-serverpack-archive-checkpoint.json").unlink()
        archive_dir.rmdir()
        f.hist.rmdir()
        request_root=f.root/"privileged-requests"
        request_root.mkdir()
        config_path=f.root/"privileged-agent.json"
        config_path.write_text(json.dumps({"agent_id":AID}))
        spec={**f.record}
        payload={
            "kind":"CapivaraPrivilegedMaterializationRequest",
            "schema_version":1,
            "action":"minecraft-serverpack-swap-phase",
            "phase":"archive-committed",
            "agent_id":AID,
            "instance_id":IID,
            "spec":spec,
        }
        (request_root/(IID+".request.json")).write_text(json.dumps(payload))
        with patch.object(helper,"REQUEST_ROOT",request_root), \
             patch.object(helper,"CONFIG_PATH",config_path), \
             patch.object(helper,"validate_runtime_spec",return_value=spec), \
             patch.object(helper,"resolve_materializer",return_value=object()), \
             patch.object(helper,"_instance_storage_root",return_value=f.storage.parent):
            result=helper.run(IID)
        self.assertEqual(result["operation"]["status"],"archived")
        self.assertEqual(json.loads(f.operation.read_text())["status"],"finalization_pending")
        actual=f.child(env=self.env)
        self.assertEqual(actual.returncode,0,actual.stderr+actual.stdout)
        self.assertEqual(json.loads(f.operation.read_text())["status"],"completed")
        self.assertEqual(json.loads(f.provision.read_text())["status"],"completed")
        self.assertEqual((f.storage/"runtime/world/level.dat").read_bytes(),b"PR981_NEW_WORLD")
        self.assertEqual(next(f.hist.glob("*/runtime.migration-rollback/world/level.dat")).read_bytes(),
                         b"PR981_OLD_WORLD")
        self.assertEqual(subprocess.run(["systemctl","is-active",self.unit],
                                       capture_output=True,text=True).stdout.strip(),"active")
        self.assertEqual(f.child(env=self.env).returncode,0)
        self.assertEqual(len(list(f.hist.iterdir())),1)

    def test_authorized_real_worker_restores_service_after_archive(self):
        f=self.f
        self.assertEqual(json.loads(f.operation.read_text())["status"],"finalization_pending")
        outcome=f.child(env=self.env)
        self.assertEqual(outcome.returncode,0,outcome.stderr+outcome.stdout)
        self.assertEqual(json.loads(f.operation.read_text())["status"],"completed")
        completion=json.loads(f.provision.read_text())
        self.assertEqual(completion["status"],"completed")
        self.assertEqual(completion["observed_state"],"running")
        self.assertEqual(
            completion["minecraft_serverpack_migration"]["finalization"]["status"],
            "already_archived")
        self.assertEqual((f.storage/"runtime/world/level.dat").read_bytes(),b"PR981_NEW_WORLD")
        archived=next(f.hist.glob("*/runtime.migration-rollback/world/level.dat"))
        self.assertEqual(archived.read_bytes(),b"PR981_OLD_WORLD")
        self.assertEqual(subprocess.run(["systemctl","is-active",self.unit],
                                       capture_output=True,text=True).stdout.strip(),"active")
        replay=f.child(env=self.env)
        self.assertEqual(replay.returncode,0,replay.stderr+replay.stdout)
        self.assertEqual(json.loads(f.operation.read_text())["status"],"completed")
        self.assertEqual(len(list(f.hist.glob("*/minecraft-serverpack-migration.json"))),1)


if __name__=="__main__":
    unittest.main()
