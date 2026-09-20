#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    runtime_dir = path.parent
    sys.path.insert(0, str(runtime_dir))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(runtime_dir))


class CustomerInstanceFileSecurityTest(unittest.TestCase):
    def test_linux_upload_is_scanned_before_destination_activation(self):
        module = load("linux_instance_files_security", ROOT / "agents/linux/runtime/instance_files_client.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            destination = root / "payload.bin"
            with patch.object(module, "require_clean", side_effect=RuntimeError("blocked by YARA-X")):
                with self.assertRaises(RuntimeError):
                    module._upload(root, "payload.bin", {"content_base64": "QUJD"}, {}, security_context={"agent_id": "a", "instance_id": "i"})
            self.assertFalse(destination.exists())
            self.assertFalse(any(root.glob(".*.upload")))

    def test_linux_extract_scans_archive_and_expanded_tree_before_materialization(self):
        module = load("linux_instance_files_extract_security", ROOT / "agents/linux/runtime/instance_files_client.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "config.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("config/server.cfg", "name=test\n")
            calls = []
            def clean(path, _context=None):
                calls.append(Path(path))
                return {"security_state": "clean"}
            with patch.object(module, "require_clean", side_effect=clean):
                result = module._extract(root, "config.zip", ".", {}, security_context={"agent_id": "a", "instance_id": "i"})
            self.assertEqual(result["security_state"], "clean")
            self.assertEqual(result["archive_security_state"], "clean")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], archive)
            self.assertTrue((root / "config/server.cfg").is_file())

    def test_windows_file_manager_uses_same_security_gates(self):
        source = (ROOT / "agents/windows/runtime/instance_files_client.py").read_text(encoding="utf-8")
        self.assertIn("from content_security import require_clean", source)
        self.assertIn("verdict=require_clean(tmp,security_context)", source)
        self.assertIn("archive_verdict=require_clean(ap,security_context)", source)
        self.assertIn("expanded_verdict=require_clean(staging,security_context)", source)

    def test_customer_ui_uses_agent_usage_bytes_and_human_root_label(self):
        source = (ROOT / "dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
        self.assertIn("usage.usage_bytes??usage.used_bytes", source)
        self.assertIn('filePath==="."?"/":\`/\${filePath}\`', source)

    def test_customer_ui_exposes_extract_only_with_permission(self):
        source = (ROOT / "dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
        self.assertIn('can("files.extract")', source)
        self.assertIn('extract.textContent="Descompactar"', source)
        self.assertIn('fileCommand("extract",itemPath,filePath)', source)
        self.assertIn("validado pelo YARA-X", source)


if __name__ == "__main__":
    unittest.main()
