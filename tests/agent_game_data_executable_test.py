#!/usr/bin/env python3
from __future__ import annotations
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
sys.path.insert(0, str(RUNTIME))
import game_data_executor
import game_data_integrity

class AgentGameDataExecutableTest(unittest.TestCase):
    def test_http_archive_declared_executable_is_owner_executable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "bedrock.zip"; target = root / "game-data"
            with zipfile.ZipFile(archive, "w") as package:
                info = zipfile.ZipInfo("bedrock_server")
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                package.writestr(info, b"binary")
                package.writestr("server.properties", b"server-port=19132\n")
            selection = {
                "game": "minecraft", "provider": "http-archive",
                "executable": "bedrock_server", "artifact_mode": "executable",
                "asset": {"url": "https://example.invalid/bedrock.zip"},
                "archive": {"type": "zip"}, "install": {},
            }
            def fake_download(url, destination):
                shutil.copy2(archive, destination)
            with mock.patch.object(game_data_executor, "_download", side_effect=fake_download):
                game_data_executor._run_http(selection, target)
            executable = target / "bedrock_server"
            self.assertTrue(executable.is_file())
            self.assertTrue(executable.stat().st_mode & stat.S_IXUSR)
            self.assertEqual(game_data_integrity.inspect_game_data(target, selection)["health"], "ok")


    def test_file_artifact_does_not_require_execute_bit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); artifact = root / "server.jar"
            artifact.write_bytes(b"jar"); artifact.chmod(0o600)
            result = game_data_integrity.inspect_game_data(root, {"executable": "server.jar", "artifact_mode": "jar"})
            self.assertEqual(result["health"], "ok")
            self.assertTrue(result["executable_ready"])

    def test_integrity_rejects_non_executable_declared_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); binary = root / "bedrock_server"
            binary.write_bytes(b"binary"); binary.chmod(0o644)
            result = game_data_integrity.inspect_game_data(root, {"executable": "bedrock_server", "artifact_mode": "executable"})
            self.assertEqual(result["health"], "degraded")
            self.assertTrue(result["executable_present"])
            self.assertFalse(result["executable_ready"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
