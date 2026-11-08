#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "core", ROOT / "agents/common"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from minecraft_serverpack_content_sync import prepare_verified_sources, ServerPackContentSyncError


class VerifiedSourceStagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.stage = self.root / "serverpack-stage"
        for path in (self.runtime / "mods", self.stage / "mods", self.root / "sources"):
            path.mkdir(parents=True)
        self.data = b"fake jar bytes only for test"
        for path in (self.runtime / "mods/a.jar", self.stage / "mods/a.jar"):
            path.write_bytes(self.data)
        (self.runtime / "world").mkdir()
        (self.runtime / "world" / "level.dat").write_bytes(b"world-must-stay")
        (self.runtime / "config").mkdir()
        (self.runtime / "config" / "customer.toml").write_text("private=true")
        import hashlib
        sha = hashlib.sha256(self.data).hexdigest()
        self.proof = {"instance_id": "inst", "content_id": "pack",
            "candidate_sha256": "c"*64, "migration_plan_sha256": "d"*64,
            "bundle": {"loader_version": "26.1.2.126", "members": [{}]},
            "parent": {"target": "modpacks/pack"},
            "children": [{"content_id": "child-a", "target": "mods/child-a",
                          "artifact": {"filename": "a.jar", "sha256": sha, "size_bytes": len(self.data)}}]}
        self.journal = {"phase": "committed", "migration_plan_sha256": "d"*64,
                        "target_loader_version": "26.1.2.126"}
        self.destination = self.root / "sources" / "candidate"

    def prepare(self):
        with patch("minecraft_serverpack_content_sync.authorize_after_agent_completion",
                   return_value=self.proof):
            return prepare_verified_sources(
                pending={}, agent_result={}, instance_id="inst",
                runtime=self.runtime, serverpack_stage=self.stage,
                committed_journal=self.journal, destination=self.destination)

    def test_stage_and_replay_never_modify_world_or_config(self):
        self.assertEqual(self.prepare()["status"], "prepared")
        self.assertEqual(self.prepare()["status"], "already_prepared")
        self.assertEqual((self.runtime/"world/level.dat").read_bytes(), b"world-must-stay")
        self.assertEqual((self.runtime/"config/customer.toml").read_text(), "private=true")
        self.assertEqual((self.destination/"children/child-a/a.jar").read_bytes(), self.data)

    def test_reject_mismatched_runtime_before_copy(self):
        (self.runtime / "mods/a.jar").write_bytes(b"changed")
        with self.assertRaisesRegex(ServerPackContentSyncError, "do not match commit"):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_common_jar_filename_with_plus_and_spaces_is_supported(self):
        child = self.proof["children"][0]
        child["artifact"]["filename"] = "Super Factory Manager (SFM)+1.2.jar"
        original = self.runtime/"mods/a.jar"
        staged = self.stage/"mods/a.jar"
        original.rename(self.runtime/"mods"/child["artifact"]["filename"])
        staged.rename(self.stage/"mods"/child["artifact"]["filename"])
        self.assertEqual(self.prepare()["status"],"prepared")

    def test_reject_uncommitted_journal(self):
        self.journal["phase"] = "swapped"
        with self.assertRaisesRegex(ServerPackContentSyncError, "not committed"):
            self.prepare()

    def test_reject_unexpected_target(self):
        self.proof["children"][0]["target"] = "world/child-a"
        with self.assertRaisesRegex(ServerPackContentSyncError, "managed mod target"):
            self.prepare()

    def test_reject_staged_symlink(self):
        (self.stage/"server-overrides").symlink_to(self.runtime/"world", target_is_directory=True)
        with self.assertRaisesRegex(ServerPackContentSyncError, "unsafe entry"):
            self.prepare()

    def test_replay_detects_corrupted_source(self):
        self.prepare()
        (self.destination/"children/child-a/a.jar").write_bytes(b"tampered")
        with self.assertRaisesRegex(ServerPackContentSyncError, "hash mismatch"):
            self.prepare()

    def test_reject_mismatched_content_id(self):
        self.proof["instance_id"] = "another"
        with self.assertRaisesRegex(ServerPackContentSyncError, "identity mismatch"):
            self.prepare()

    def test_reject_replaced_destination_symlink(self):
        self.destination.symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaisesRegex(ServerPackContentSyncError, "symlink destination"):
            self.prepare()

    def test_candidate_attestation_is_required(self):
        with self.assertRaisesRegex(ServerPackContentSyncError, "has not been attested"):
            prepare_verified_sources(
                pending={}, agent_result={}, instance_id="inst",
                runtime=self.runtime, serverpack_stage=self.stage,
                committed_journal=self.journal, destination=self.destination)


if __name__ == "__main__":
    unittest.main()
