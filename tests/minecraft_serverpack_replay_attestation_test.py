#!/usr/bin/env python3
"""Server Pack replay must not accept a changed unverified artifact digest."""
from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load(platform):
    root=ROOT/f"agents/{platform}/runtime"
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location(
        f"serverpack_replay_{platform}",root/"content_client.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def child_command(digest="a"*64,size=1024):
    return {"instance_id":"scratch","content_id":"mb-one",
            "game_id":"minecraft","content_type":"mod","provider":"local",
            "version":"a"*32,"revision":2,"checksum":"revision-two",
            "desired_state":"installed","target":"mods/mb-one",
            "artifact":{"provider":"local","serverpack_child_v1":True,
                        "serverpack_loader_version":"26.1.2.109",
                        "sha256":digest,"size_bytes":size}}
def installed(cmd):
    return {"instance_id":"scratch","content_id":"mb-one",
            "game_id":"minecraft","provider":"local",
            "content_type":"mod","package_id":None,"target":"mods/mb-one",
            "status":"applied","applied_revision":1,
            "applied_checksum":"revision-one",
            "security_state":"clean","security_policy_version":1,
            "installed_version":cmd["version"],
            "managed_path":"/unused/scratch/mods/mb-one",
            "source_sha256":"a"*64,"source_size_bytes":1024}


class ServerPackReplayAttestationTest(unittest.TestCase):
    def test_changed_digest_or_size_never_reuses_existing_revision(self):
        for platform in ("linux","windows"):
            mod=load(platform)
            cmd=child_command()
            old=installed(cmd)
            good=mod._source_metadata(cmd)
            self.assertTrue(mod._serverpack_replay_valid(old,cmd,good))
            cases=(child_command(digest="0"*64),
                   child_command(size=2048),child_command(digest="invalid"))
            for changed in cases:
                with self.subTest(platform=platform,artifact=changed["artifact"]):
                    meta=mod._source_metadata(changed)
                    self.assertFalse(mod._serverpack_replay_valid(old,changed,meta))
            self.assertFalse(mod._serverpack_replay_valid(
                {**old,"source_sha256":None},cmd,good))
            self.assertFalse(mod._serverpack_replay_valid(
                {**old,"source_size_bytes":None},cmd,good))
    def test_metadata_only_reuse_checks_stopped_state_and_loader(self):
        for platform in ("linux","windows"):
            mod=load(platform)
            cmd=child_command()
            old=installed(cmd)
            meta=mod._source_metadata(cmd)
            with patch.object(mod,"_managed_path_current",return_value=True),\
                 patch.object(mod,"_owned",return_value=({},Path("/scratch"))),\
                 patch.object(mod,"verify_installed_neoforge",return_value={
                     "loader_version":"26.1.2.109"}),\
                 patch.object(mod.instance_runtime,"status",return_value={
                     "observed_state":"stopped"}):
                self.assertTrue(mod._reuse_installed({"agent_id":"test"},old,cmd,meta))
                corrupt=child_command(digest="0"*64)
                self.assertFalse(mod._reuse_installed({"agent_id":"test"},old,
                    corrupt,mod._source_metadata(corrupt)))
            with patch.object(mod,"_managed_path_current",return_value=True),\
                 patch.object(mod,"_owned",return_value=({},Path("/scratch"))),\
                 patch.object(mod.instance_runtime,"status",return_value={
                     "observed_state":"running"}):
                self.assertFalse(mod._reuse_installed({"agent_id":"test"},old,cmd,meta))
    def test_same_revision_fast_path_cannot_promote_changed_digest(self):
        for platform in ("linux","windows"):
            mod=load(platform)
            valid=child_command()
            previous=installed(valid)
            previous.update({"applied_revision":2,"applied_checksum":"revision-two"})
            changed=child_command(digest="0"*64)
            with self.subTest(platform=platform),tempfile.TemporaryDirectory() as td:
                state=Path(td)/"state.json"
                state.write_text(json.dumps(previous))
                with patch.object(mod,"_state_path",return_value=state),\
                     patch.object(mod,"_managed_path_current",return_value=True),\
                     patch.object(mod,"_install",side_effect=ValueError(
                         "expected archive SHA-256 mismatch")) as install:
                    result=mod._apply({"agent_id":"scratch-agent"},changed)
                    self.assertEqual(result["status"],"failed")
                    self.assertIn("SHA-256 mismatch",result["last_error"])
                    install.assert_called_once()
                    self.assertEqual(result["applied_checksum"],"revision-two")
                    self.assertEqual(result["source_sha256"],"a"*64)
                    self.assertEqual(result["source_size_bytes"],1024)
                # Different attestation, identical revision/checksum cannot
                # fast-path to 'applied' without rechecking the new source.
                self.assertTrue(state.is_file())

if __name__=="__main__":
    unittest.main()
