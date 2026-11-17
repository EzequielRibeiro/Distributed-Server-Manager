"""Opt-in real privileged dispatcher + real systemd inactive-state guard.

Fixture is a disposable Minecraft Server Pack *filesystem* with a sleep-only
systemd unit, not a live Minecraft server. Request/result protocol and root
materializer functions are real. No installed DSM paths are modified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from tests import minecraft_serverpack_privileged_root_test as root_fixtures
from tests.minecraft_serverpack_migration_swap_test import module as swap

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    os.environ.get("CAPIVARA_RUN_SYSTEMD_FINALIZATION_E2E") == "1"
    and hasattr(os, "geteuid") and os.geteuid() == 0,
    "requires explicit opt-in and root on isolated Linux systemd host",
)
class PrivilegedRealSystemdE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root_fixtures.ServerPackMigrationRootTest.setUpClass()
        cls.helper = root_fixtures.ServerPackMigrationRootTest.helper

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="dsm-pr981-privileged-")
        self.addCleanup(self.tmp.cleanup)
        self.pool=Path(self.tmp.name)/"pool"
        self.pool.mkdir()
        self.iid="pr855-priv-"+uuid.uuid4().hex[:9]
        self.instance=self.pool/self.iid
        self.instance.mkdir()
        (self.instance/"runtime").mkdir()
        self.spec={
            "instance_id":self.iid,
            "game_id":"minecraft",
            "environment_id":"minecraft.java.neoforge",
            "instance_state_root":str(self.instance),
            "working_directory":str(self.instance/"runtime"),
        }
        pool_patch=patch.object(self.helper,"_instance_storage_root",return_value=self.pool)
        pool_patch.start()
        self.addCleanup(pool_patch.stop)
        self.agent="pr839-isolated-agent"
        self.spec["agent_id"]=self.agent
        self.unit="capivara-instance-"+self.iid+".service"
        self.unitfile=Path("/run/systemd/system")/self.unit
        self.request_root=Path(self.tmp.name)/"requests"
        self.request_root.mkdir()
        self.config_file=Path(self.tmp.name)/"agent.json"
        self.config_file.write_text(json.dumps({"agent_id":self.agent}))
        self.unitfile.write_text(
            "[Unit]\nDescription=DSM PR981 disposable privileged fixture\n"
            "[Service]\nType=simple\nExecStart=/usr/bin/sleep 35\n"
            "Restart=no\nTimeoutStopSec=3\n"
        )
        self.addCleanup(self.clean_unit)
        subprocess.run(["systemctl","daemon-reload"],check=True,timeout=10)
        self.patchers=[
            patch.object(self.helper,"REQUEST_ROOT",self.request_root),
            patch.object(self.helper,"CONFIG_PATH",self.config_file),
            patch.object(self.helper,"validate_runtime_spec",return_value=self.spec),
            patch.object(self.helper,"resolve_materializer",return_value=object()),
        ]
        for item in self.patchers:
            item.start();self.addCleanup(item.stop)

    def clean_unit(self):
        subprocess.run(["systemctl","stop",self.unit],capture_output=True,timeout=10)
        self.unitfile.unlink(missing_ok=True)
        subprocess.run(["systemctl","daemon-reload"],capture_output=True,timeout=10)
        subprocess.run(["systemctl","reset-failed",self.unit],capture_output=True,timeout=10)

    def _fixture_runtime(self, root, version, marker):
        root.mkdir()
        libs=root/"libraries/net/neoforged/neoforge"/version
        libs.mkdir(parents=True)
        args=libs/"unix_args.txt"
        args.write_bytes(b"--loader "+version.encode()+b"\n")
        (root/"capivara-launch.args").write_bytes(args.read_bytes())
        (root/"user_jvm_args.txt").write_text("-Xmx1G\n")
        (root/"world").mkdir()
        (root/"world/level.dat").write_bytes(marker)

    def commit_fixture(self):
        (self.instance/"runtime").rmdir()
        self._fixture_runtime(self.instance/"runtime","26.1.2.94",b"ORIGINAL")
        self._fixture_runtime(self.instance/"runtime.migration-stage","26.1.2.109",b"NEW")
        swap.prepare(self.instance,migration_plan_sha256="b"*64,
                     target_loader_version="26.1.2.109",
                     backup={"backup_id":"backup-fixture","sha256":"d"*64,
                             "size_bytes":1234,"integrity_verified":True})
        swap.switch(self.instance)
        swap.commit(self.instance,readiness_passed=True)

    def request_archive(self):
        payload={
            "kind":"CapivaraPrivilegedMaterializationRequest",
            "schema_version":1,
            "action":"minecraft-serverpack-swap-phase",
            "phase":"archive-committed",
            "agent_id":self.agent,
            "instance_id":self.iid,
            "spec":self.spec,
        }
        (self.request_root/(self.iid+".request.json")).write_text(json.dumps(payload))
        return self.helper.run(self.iid)

    def test_real_helper_archives_only_inactive_unit(self):
        self.commit_fixture()
        initial=self.helper._serverpack_require_inactive(self.iid)
        self.assertIsNone(initial)
        archived=self.request_archive()
        self.assertEqual(archived["operation"]["status"],"archived")
        self.assertEqual(self.request_archive()["operation"]["status"],"already_archived")
        history=Path(archived["operation"]["history"])
        self.assertEqual((history/"runtime.migration-rollback/world/level.dat").read_bytes(),b"ORIGINAL")
        self.assertEqual((self.instance/"runtime/world/level.dat").read_bytes(),b"NEW")

    def test_real_helper_rejects_active_unit_without_archiving(self):
        self.commit_fixture()
        subprocess.run(["systemctl","start",self.unit],check=True,timeout=10)
        with self.assertRaisesRegex(RuntimeError,"inactive loaded"):
            self.request_archive()
        self.assertTrue((self.instance/".dsm/minecraft-serverpack-migration.json").is_file())
        self.assertTrue((self.instance/"runtime.migration-rollback").is_dir())
        self.assertEqual((self.instance/"runtime/world/level.dat").read_bytes(),b"NEW")

    def test_real_helper_rejects_tampered_rollback(self):
        self.commit_fixture()
        (self.instance/"runtime.migration-rollback/world/level.dat").write_bytes(b"TAMPER")
        with self.assertRaises(Exception):
            self.request_archive()
        self.assertTrue((self.instance/".dsm/minecraft-serverpack-migration.json").is_file())


if __name__=="__main__":
    unittest.main()
