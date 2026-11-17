"""Real disposable filesystem swap + Agent JAR attestation + recovery.

No systemd service, game process, or production instance is touched.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
for base in (ROOT/"core",ROOT/"agents/common",ROOT/"agents/linux/runtime"):
    if str(base) not in sys.path:sys.path.insert(0,str(base))

import minecraft_serverpack_migration_swap as swap
from minecraft_serverpack_physical_manifest import (
    MinecraftServerPackPhysicalManifestError,attest_serverpack_mods,
)

BACKUP={"backup_id":"backup-physical","sha256":"d"*64,"size_bytes":1234,"integrity_verified":True}
PLAN="b"*64
LOADER="26.1.2.109"
PAYLOAD=b"pr1013 disposable managed mod payload"


def make_runtime(root:Path,version:str,world:bytes)->None:
    lib=root/"libraries/net/neoforged/neoforge"/version
    lib.mkdir(parents=True)
    (lib/"unix_args.txt").write_text("--loader "+version+"\n")
    (root/"capivara-launch.args").write_bytes((lib/"unix_args.txt").read_bytes())
    (root/"user_jvm_args.txt").write_text("-Xmx1G\n")
    (root/"world").mkdir()
    (root/"world/level.dat").write_bytes(world)


def manifest():
    return {"provider":"local","provider_project_id":"cf-1148445",
        "provider_version_id":"v14","minecraft_version":"26.1.2",
        "loader_id":"neoforge","loader_version":LOADER,
        "manifest_kind":"serverpack-local-v1","override_roots":[],
        "members":[{"content_id":"mod-a","path":"mods/mod-a.jar","required":True,
            "artifact":{"provider":"local","serverpack_child_v1":True,
                "ephemeral_upload":True,"bundle_parent_content_id":"atm11",
                "bundle_member":"mods/mod-a.jar","serverpack_loader":"neoforge",
                "serverpack_loader_version":LOADER,
                "sha256":hashlib.sha256(PAYLOAD).hexdigest(),
                "size_bytes":len(PAYLOAD)}}]}


class PhysicalSwapIntegrationE2E(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="pr1013-physical-real-swap-")
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        make_runtime(self.root/"runtime","26.1.2.94",b"ORIGINAL-WORLD")
        make_runtime(self.root/"runtime.migration-stage",LOADER,b"STAGED-WORLD")
        self.jar=self.root/"runtime.migration-stage/mods/mod-a.jar"
        self.jar.parent.mkdir(parents=True)
        self.jar.write_bytes(PAYLOAD)
        self.bundle=manifest()

    def attest(self):
        return attest_serverpack_mods(self.root/"runtime",
            instance_id="pr855-physical-swap",content_id="atm11",bundle=self.bundle)

    def switch(self):
        swap.prepare(self.root,migration_plan_sha256=PLAN,
            target_loader_version=LOADER,backup=BACKUP)
        swap.switch(self.root)

    def test_real_swap_passes_attestation_then_commits_retaining_world_backup(self):
        self.switch()
        proof=self.attest()
        self.assertEqual(proof["status"],"physical_mods_verified")
        self.assertEqual(proof["mod_count"],1)
        committed=swap.commit(self.root,readiness_passed=True)
        self.assertEqual(committed["status"],"committed")
        self.assertEqual((self.root/"runtime/world/level.dat").read_bytes(),b"STAGED-WORLD")
        self.assertEqual((self.root/"runtime.migration-rollback/world/level.dat").read_bytes(),b"ORIGINAL-WORLD")
        archived=swap.archive_committed(self.root)
        self.assertEqual(archived["status"],"archived")
        self.assertEqual((Path(archived["history"])/"runtime.migration-rollback/world/level.dat").read_bytes(),b"ORIGINAL-WORLD")

    def test_mismatched_jar_after_swap_rejects_attestation_and_recovers_world(self):
        self.switch()
        installed=self.root/"runtime/mods/mod-a.jar"
        installed.write_bytes(b"X"*len(PAYLOAD))
        with self.assertRaisesRegex(MinecraftServerPackPhysicalManifestError,"SHA-256"):
            self.attest()
        result=swap.recover(self.root)
        self.assertEqual(result["status"],"recovered")
        self.assertEqual((self.root/"runtime/world/level.dat").read_bytes(),b"ORIGINAL-WORLD")
        self.assertEqual((self.root/"runtime.migration-failed/mods/mod-a.jar").read_bytes(),b"X"*len(PAYLOAD))
        self.assertEqual(swap.recover(self.root)["status"],"already_recovered")

    def test_tamper_after_physical_attestation_blocks_commit_and_can_recover(self):
        self.switch()
        self.attest()
        (self.root/"runtime/mods/mod-a.jar").write_bytes(b"Y"*len(PAYLOAD))
        with self.assertRaisesRegex(swap.MinecraftServerPackMigrationSwapError,"managed runtime changed"):
            swap.commit(self.root,readiness_passed=True)
        self.assertEqual(swap.recover(self.root)["status"],"recovered")
        self.assertEqual((self.root/"runtime/world/level.dat").read_bytes(),b"ORIGINAL-WORLD")


if __name__=="__main__":unittest.main()