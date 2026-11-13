"""Offline versioned supervisor staging: no service, daemon or DSM install."""
from __future__ import annotations
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("supervisor_stage", str(ROOT/"update-manager/game-uptime-supervisor-stage.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
stage = importlib.util.module_from_spec(spec)
loader.exec_module(stage)


class SupervisorStageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dsm928-supervisor-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root/"console_supervisor.py"
        self.src.write_bytes(b"print('isolated')\n")
        self.versions = self.root/"versions"
        self.versions.mkdir(mode=0o700)
        self.sha = hashlib.sha256(self.src.read_bytes()).hexdigest()

    def test_stages_content_addressed_readonly_and_idempotent(self):
        first = stage.stage_supervisor(self.src, self.versions, expected_sha256=self.sha)
        dest = Path(first["path"])
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.stat().st_mode & 0o777, 0o444)
        self.assertFalse(first["systemd_integrated"])
        self.assertFalse(first["live_no_drain_authorized"])
        second = stage.stage_supervisor(self.src, self.versions, expected_sha256=self.sha)
        self.assertTrue(second["already_present"])

    def test_digest_mismatch_leaves_no_file(self):
        with self.assertRaises(stage.SupervisorIsolationError):
            stage.stage_supervisor(self.src, self.versions, expected_sha256="0"*64)
        self.assertEqual(list(self.versions.iterdir()), [])

    def test_source_symlink_rejected(self):
        link = self.root/"link"
        link.symlink_to(self.src)
        with self.assertRaises(stage.SupervisorIsolationError):
            stage.stage_supervisor(link, self.versions, expected_sha256=self.sha)

    def test_destination_symlink_rejected(self):
        (self.versions/("console-supervisor-"+self.sha+".py")).symlink_to(self.src)
        with self.assertRaises(stage.SupervisorIsolationError):
            stage.stage_supervisor(self.src, self.versions, expected_sha256=self.sha)

    def test_world_writable_directory_rejected(self):
        self.versions.chmod(0o777)
        with self.assertRaises(stage.SupervisorIsolationError):
            stage.stage_supervisor(self.src, self.versions, expected_sha256=self.sha)

    def test_corrupt_existing_file_rejected(self):
        (self.versions/("console-supervisor-"+self.sha+".py")).write_bytes(b"wrong")
        with self.assertRaises(stage.SupervisorIsolationError):
            stage.stage_supervisor(self.src, self.versions, expected_sha256=self.sha)


if __name__=="__main__":
    unittest.main()
