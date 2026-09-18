#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def linux_archive() -> bytes:
    buffer = io.BytesIO()
    payload = b'#!/usr/bin/env python3\nimport sys\nprint("1.20.0")\n'
    with tarfile.open(fileobj=buffer, mode="w:gz") as package:
        info = tarfile.TarInfo("yara-x/yr")
        info.size = len(payload)
        info.mode = 0o755
        package.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def windows_archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("yara-x/yr.exe", b"portable-test")
    return buffer.getvalue()


class ManagedYaraXEngineTest(unittest.TestCase):
    def test_official_pins_and_architecture_mapping(self):
        linux = load(ROOT / "agents/linux/runtime/security_yarax.py", "yarax_linux_specs")
        windows = load(ROOT / "agents/windows/runtime/security_yarax.py", "yarax_windows_specs")

        self.assertEqual(linux.artifact_spec("amd64")["sha256"], "cabb8df46492fff59c51261302c71ed9cb2cef393d3f0ca560801a34a8e24cbe")
        self.assertEqual(linux.artifact_spec("arm64")["sha256"], "c1d6f63a6fe55c17b5ddbfcb89d34599b737226a683ee492b12d92d1d541f304")
        self.assertEqual(windows.artifact_spec("AMD64")["sha256"], "b1e2840bac593aea353d2b2b341f5a862c9d61c0c406d9abbbad9e1fa35163a1")
        with self.assertRaises(RuntimeError):
            linux.artifact_spec("riscv64")
        with self.assertRaises(RuntimeError):
            windows.artifact_spec("arm64")

    def test_linux_install_verifies_checksum_and_activates_version_atomically(self):
        module = load(ROOT / "agents/linux/runtime/security_yarax.py", "yarax_linux_install")
        archive = linux_archive()
        digest = hashlib.sha256(archive).hexdigest()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.STATE_ROOT = root
            module.TOOL_ROOT = root / "tools" / "yara-x"
            module.CURRENT = module.TOOL_ROOT / "current.json"
            module.ARTIFACTS["x86_64"]["sha256"] = digest

            with patch.object(module.platform, "machine", return_value="x86_64"), patch.object(
                module.urllib.request, "urlopen", return_value=io.BytesIO(archive)
            ):
                result = module.install()

            self.assertTrue(result["functional"])
            self.assertEqual(result["installed_version"], "1.20.0")
            current = json.loads(module.CURRENT.read_text(encoding="utf-8"))
            self.assertEqual(current["version"], "1.20.0")
            self.assertTrue(Path(current["binary"]).is_file())

    def test_checksum_failure_preserves_last_known_good_pointer(self):
        module = load(ROOT / "agents/linux/runtime/security_yarax.py", "yarax_linux_rollback")
        archive = linux_archive()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.STATE_ROOT = root
            module.TOOL_ROOT = root / "tools" / "yara-x"
            module.CURRENT = module.TOOL_ROOT / "current.json"
            previous = module.TOOL_ROOT / "versions" / "old" / "yr"
            previous.parent.mkdir(parents=True)
            previous.write_text("#!/bin/sh\necho 1.20.0\n", encoding="utf-8")
            previous.chmod(0o755)
            payload = {
                "schema_version": 1,
                "engine": "yara-x",
                "version": "old",
                "architecture": "x86_64",
                "binary": str(previous.resolve()),
                "sha256": "old",
                "artifact": "old",
            }
            module.CURRENT.parent.mkdir(parents=True, exist_ok=True)
            module.CURRENT.write_text(json.dumps(payload), encoding="utf-8")
            before = module.CURRENT.read_bytes()
            module.ARTIFACTS["x86_64"]["sha256"] = "0" * 64

            with patch.object(module.platform, "machine", return_value="x86_64"), patch.object(
                module.urllib.request, "urlopen", return_value=io.BytesIO(archive)
            ):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    module.install()

            self.assertEqual(module.CURRENT.read_bytes(), before)
            self.assertTrue(previous.is_file())

    def test_windows_install_uses_verified_versioned_store(self):
        module = load(ROOT / "agents/windows/runtime/security_yarax.py", "yarax_windows_install")
        archive = windows_archive()
        digest = hashlib.sha256(archive).hexdigest()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.STATE_ROOT = root
            module.TOOL_ROOT = root / "tools" / "yara-x"
            module.CURRENT = module.TOOL_ROOT / "current.json"
            module.ARTIFACTS["x86_64"]["sha256"] = digest

            with patch.object(module.platform, "machine", return_value="AMD64"), patch.object(
                module.urllib.request, "urlopen", return_value=io.BytesIO(archive)
            ), patch.object(module, "_probe", return_value="1.20.0"):
                result = module.install()

            self.assertTrue(result["functional"])
            self.assertEqual(result["installed_version"], "1.20.0")
            current = json.loads(module.CURRENT.read_text(encoding="utf-8"))
            self.assertTrue(Path(current["binary"]).name.lower() == "yr.exe")

    def test_content_security_prefers_managed_engine_but_keeps_explicit_override(self):
        for platform_name in ("linux", "windows"):
            with self.subTest(platform=platform_name):
                runtime = ROOT / "agents" / platform_name / "runtime"
                old_path = list(os.sys.path)
                try:
                    os.sys.path.insert(0, str(runtime))
                    security = load(runtime / "content_security.py", f"content_security_managed_{platform_name}")
                    with patch.object(security, "_managed_yarax_binary", return_value="/managed/yr"):
                        with patch.dict(os.environ, {"CAPIVARA_YARAX_BIN": ""}, clear=False):
                            with patch.object(security.shutil, "which", return_value="/usr/bin/yr"):
                                self.assertEqual(security._binary(), "/managed/yr")
                finally:
                    os.sys.path[:] = old_path


if __name__ == "__main__":
    unittest.main()
