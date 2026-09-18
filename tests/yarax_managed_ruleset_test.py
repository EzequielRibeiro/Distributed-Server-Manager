#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_runtime(platform_name: str, filename: str, module_name: str):
    runtime = ROOT / "agents" / platform_name / "runtime"
    previous = list(sys.path)
    sys.path.insert(0, str(runtime))
    try:
        spec = importlib.util.spec_from_file_location(module_name, runtime / filename)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = previous


class ManagedYaraXRulesetTest(unittest.TestCase):
    def test_bundled_ruleset_is_pinned_and_contains_blocking_eicar_signature(self):
        for platform_name in ("linux", "windows"):
            with self.subTest(platform=platform_name):
                module = load_runtime(platform_name, "security_yarax_rules.py", f"y2_rules_{platform_name}")
                digest = hashlib.sha256(module.RULESET_CONTENT.encode("utf-8")).hexdigest()
                self.assertEqual(digest, module.RULESET_SHA256)
                self.assertEqual(module.RULESET_VERSION, "2026.09.18.1")
                self.assertIn("Capivara_EICAR_Test_File", module.RULESET_CONTENT)
                self.assertIn(": block malware test", module.RULESET_CONTENT)

    def test_linux_install_activates_verified_ruleset_atomically(self):
        module = load_runtime("linux", "security_yarax_rules.py", "y2_linux_install")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.STATE_ROOT = root
            module.RULESET_ROOT = root / "security" / "yara-x" / "rulesets"
            module.CURRENT = module.RULESET_ROOT / "current.json"
            fake_engine = root / "yr"
            fake_engine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_engine.chmod(0o755)

            with patch.object(module, "managed_binary", return_value=str(fake_engine)), patch.object(
                module, "_validate_rules", return_value=None
            ):
                result = module.install()

            self.assertTrue(result["installed"])
            self.assertTrue(result["checksum_valid"])
            self.assertEqual(result["ruleset_version"], module.RULESET_VERSION)
            current = json.loads(module.CURRENT.read_text(encoding="utf-8"))
            self.assertEqual(current["sha256"], module.RULESET_SHA256)
            self.assertTrue(Path(current["rules_path"]).is_file())

    def test_tampered_rule_file_or_pointer_is_rejected_fail_closed(self):
        module = load_runtime("linux", "security_yarax_rules.py", "y2_linux_tamper")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.STATE_ROOT = root
            module.RULESET_ROOT = root / "security" / "yara-x" / "rulesets"
            module.CURRENT = module.RULESET_ROOT / "current.json"
            rules = module.RULESET_ROOT / "versions" / module.RULESET_VERSION / "baseline.yar"
            rules.parent.mkdir(parents=True)
            rules.write_text(module.RULESET_CONTENT, encoding="utf-8")
            module.CURRENT.parent.mkdir(parents=True, exist_ok=True)
            module.CURRENT.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "engine": "yara-x",
                        "version": module.RULESET_VERSION,
                        "rules_path": str(rules.resolve()),
                        "sha256": module.RULESET_SHA256,
                        "rules_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(module.managed_rules_path(), str(rules.resolve()))

            rules.write_text(module.RULESET_CONTENT + "\n// tampered\n", encoding="utf-8")
            self.assertIsNone(module.managed_rules_path())

            rules.write_text(module.RULESET_CONTENT, encoding="utf-8")
            current = json.loads(module.CURRENT.read_text(encoding="utf-8"))
            current["sha256"] = "0" * 64
            module.CURRENT.write_text(json.dumps(current), encoding="utf-8")
            self.assertIsNone(module.managed_rules_path())

    def test_failed_staging_preserves_existing_current_pointer(self):
        module = load_runtime("linux", "security_yarax_rules.py", "y2_linux_preserve")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.STATE_ROOT = root
            module.RULESET_ROOT = root / "security" / "yara-x" / "rulesets"
            module.CURRENT = module.RULESET_ROOT / "current.json"
            module.CURRENT.parent.mkdir(parents=True)
            module.CURRENT.write_text('{"sentinel":"keep"}\n', encoding="utf-8")
            before = module.CURRENT.read_bytes()
            fake_engine = root / "yr"
            fake_engine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_engine.chmod(0o755)

            with patch.object(module, "managed_binary", return_value=str(fake_engine)), patch.object(
                module, "_validate_rules", side_effect=RuntimeError("invalid rules")
            ):
                with self.assertRaisesRegex(RuntimeError, "invalid rules"):
                    module.install()

            self.assertEqual(module.CURRENT.read_bytes(), before)

    def test_windows_install_has_same_persistent_contract(self):
        module = load_runtime("windows", "security_yarax_rules.py", "y2_windows_install")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module.STATE_ROOT = root
            module.RULESET_ROOT = root / "security" / "yara-x" / "rulesets"
            module.CURRENT = module.RULESET_ROOT / "current.json"
            fake_engine = root / "yr.exe"
            fake_engine.write_bytes(b"portable-test")

            with patch.object(module, "managed_binary", return_value=str(fake_engine)), patch.object(
                module, "_validate_rules", return_value=None
            ):
                result = module.install()

            self.assertEqual(result["state"], "ready")
            self.assertEqual(result["ruleset_version"], module.RULESET_VERSION)

    def test_content_security_prefers_managed_rules_and_reports_metadata(self):
        for platform_name in ("linux", "windows"):
            with self.subTest(platform=platform_name):
                security = load_runtime(platform_name, "content_security.py", f"y2_security_{platform_name}")
                with tempfile.TemporaryDirectory() as td:
                    rules = Path(td) / "baseline.yar"
                    rules.write_text("rule x { condition: false }\n", encoding="utf-8")
                    with patch.object(security, "_managed_yarax_rules_path", return_value=str(rules)), patch.object(
                        security, "_managed_rules_status",
                        return_value={
                            "ruleset_version": "2026.09.18.1",
                            "sha256": "abc",
                            "checksum_valid": True,
                        },
                    ), patch.object(security, "_binary", return_value="/managed/yr"), patch.dict(
                        os.environ, {"CAPIVARA_YARAX_RULES_PATH": ""}, clear=False
                    ):
                        self.assertEqual(security._rules_path(), rules)
                        status = security.scanner_status()
                        self.assertTrue(status["ready"])
                        self.assertEqual(status["ruleset_version"], "2026.09.18.1")
                        self.assertEqual(status["ruleset_sha256"], "abc")
                        self.assertTrue(status["ruleset_checksum_valid"])

    def test_cli_surfaces_engine_and_ruleset_operations(self):
        cap = (ROOT / "bin" / "cap").read_text(encoding="utf-8")
        linux = (ROOT / "agents" / "linux" / "runtime" / "local_cli.py").read_text(encoding="utf-8")
        windows = (ROOT / "agents" / "windows" / "runtime" / "admin_gui_backend.py").read_text(encoding="utf-8")
        self.assertIn("cap agent security yara rules status|install", cap)
        self.assertIn("yarax_rules_install", linux)
        self.assertIn("agent security yara rules install", windows)


if __name__ == "__main__":
    unittest.main()
