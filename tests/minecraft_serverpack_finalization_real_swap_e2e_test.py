"""End-to-end crash replay with the actual Server Pack swap/archival engine.

Runs against disposable storage only; does not create any systemd service or
touch an existing instance. Uses real prepare/switch/commit/archive_committed,
the real checkpoint verifier, and the finalization coordinator.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/common"))
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
import minecraft_serverpack_migration_swap as swap
from minecraft_serverpack_finalization_completion import finish_pending_migration

PLAN="b"*64
LOADER="26.1.2.109"
ID="pr855-archive-lifecycle"
AGENT="pr839-isolated-agent"
BACKUP={"backup_id":"backup-1","sha256":"d"*64,"size_bytes":1234,"integrity_verified":True}


def runtime(path, version, world):
    libs=path/"libraries/net/neoforged/neoforge"/version
    libs.mkdir(parents=True)
    (libs/"unix_args.txt").write_text("--loader "+version+"\n")
    (path/"capivara-launch.args").write_bytes((libs/"unix_args.txt").read_bytes())
    (path/"user_jvm_args.txt").write_text("-Xmx1G\n")
    (path/"world").mkdir()
    (path/"world/level.dat").write_bytes(world)


class RealSwapReplayE2E(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="dsm-pr981-real-swap-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        runtime(self.root/"runtime","26.1.2.94",b"ORIGINAL_WORLD")
        runtime(self.root/"runtime.migration-stage",LOADER,b"NEW_WORLD")
        swap.prepare(self.root,migration_plan_sha256=PLAN,target_loader_version=LOADER,backup=BACKUP)
        swap.switch(self.root)
        swap.commit(self.root,readiness_passed=True)
        self.op={
            "instance_id":ID,"agent_id":AGENT,"operation":"minecraft_serverpack_migration",
            "status":"finalization_pending","migration_plan_sha256":PLAN,
        }
        self.res={
            "instance_id":ID,"provisioning_id":"pr981-swap-1",
            "status":"running","current_step":"minecraft_serverpack_finalization",
            "finalization_state":"pending",
            "minecraft_serverpack_migration":{
                "status":"finalization_pending","trace":["committed","finalization_pending"],
                "migration_plan_sha256":PLAN,"target_loader_version":LOADER,
                "commit":{"initial_active_state":"active"},
                "backup":BACKUP.copy(),
            },
        }
        self.state="inactive"
        self.events=[]
        self.fail=None

    def archive(self):
        self.events.append("archive")
        if self.fail=="archive":
            raise RuntimeError("injected archive interruption")
        return swap.archive_committed(self.root)

    def restart(self,expected):
        self.events.append("restart")
        if self.fail=="restart":
            raise RuntimeError("injected restart failure")
        self.state=expected
        return expected

    def publish(self,record):
        self.events.append("publish")
        if self.fail=="publish":
            raise RuntimeError("injected publication crash")
        self.res=dict(record)

    def write_op(self,record):
        self.events.append("operation")
        if self.fail=="operation":
            raise RuntimeError("injected final journal interruption")
        self.op=dict(record)

    def run_recovery(self):
        return finish_pending_migration(
            instance_id=ID,agent_id=AGENT,instance_root=self.root,
            operation=dict(self.op),provisioning=dict(self.res),
            verify_backup=lambda data:data==BACKUP,
            observe_service=lambda:self.state,archive_committed=self.archive,
            restore_service=self.restart,write_provisioning=self.publish,
            write_operation=self.write_op,
        )

    def assert_preserved(self):
        self.assertEqual((self.root/"runtime/world/level.dat").read_bytes(),b"NEW_WORLD")
        archived=list((self.root/".dsm/migration-history").glob("*/runtime.migration-rollback/world/level.dat"))
        self.assertEqual(len(archived),1)
        self.assertEqual(archived[0].read_bytes(),b"ORIGINAL_WORLD")

    def test_full_real_archive_then_restart(self):
        self.assertEqual(self.run_recovery()["status"],"completed")
        self.assertEqual(self.events,["archive","restart","publish","operation"])
        self.assert_preserved()
        self.assertEqual(self.op["status"],"completed")

    def test_real_archive_interruption_then_idempotent_replay(self):
        self.fail="archive"
        with self.assertRaises(RuntimeError):self.run_recovery()
        self.assertEqual(self.op["status"],"finalization_pending")
        self.fail=None
        self.assertEqual(self.run_recovery()["status"],"completed")
        self.assert_preserved()

    def test_crash_after_archival_before_restart(self):
        swap.archive_committed(self.root)
        self.assertEqual(self.run_recovery()["status"],"completed")
        self.assertEqual(self.events,["restart","publish","operation"])
        self.assert_preserved()

    def test_crash_after_restart_before_publication(self):
        swap.archive_committed(self.root)
        self.state="active"
        self.assertEqual(self.run_recovery()["status"],"completed")
        self.assertEqual(self.events,["publish","operation"])
        self.assert_preserved()

    def test_crash_after_publish_finishes_outer_only(self):
        self.fail="operation"
        with self.assertRaises(RuntimeError):self.run_recovery()
        self.assertEqual(self.res["status"],"completed")
        self.fail=None
        self.events.clear()
        self.assertEqual(self.run_recovery()["status"],"operation_reconciled")
        self.assertEqual(self.events,["operation"])
        self.assert_preserved()

    def test_rollback_modified_refuses_archival(self):
        (self.root/"runtime.migration-rollback/world/level.dat").write_bytes(b"TAMPER")
        with self.assertRaises(Exception):self.run_recovery()
        self.assertEqual(self.op["status"],"finalization_pending")
        self.assertEqual((self.root/"runtime/world/level.dat").read_bytes(),b"NEW_WORLD")


if __name__=="__main__":
    unittest.main()
