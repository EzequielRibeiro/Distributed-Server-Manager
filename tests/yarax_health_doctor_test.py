#!/usr/bin/env python3
from __future__ import annotations

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
    old_path = list(sys.path)
    sys.path.insert(0, str(runtime))
    try:
        spec = importlib.util.spec_from_file_location(module_name, runtime / filename)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old_path


class YaraXHealthDoctorTest(unittest.TestCase):
    def _scanner(self, platform_name: str):
        return load_runtime(platform_name, "content_security.py", f"y3_security_{platform_name}_{id(self)}")

    def test_missing_engine_is_reported_with_last_error(self):
        for platform_name in ("linux", "windows"):
            with self.subTest(platform=platform_name):
                module = self._scanner(platform_name)
                with tempfile.TemporaryDirectory() as td, patch.object(
                    module, "_managed_engine_status", return_value={"state": "missing", "managed": True}
                ), patch.object(module, "_managed_rules_status", return_value={"state": "missing", "managed": True}), patch.object(
                    module, "_managed_yarax_binary", return_value=None
                ), patch.object(module, "_managed_yarax_rules_path", return_value=None), patch.object(
                    module.shutil, "which", return_value=None
                ), patch.object(module, "LEGACY_RULES_PATH", Path(td) / "missing-rules"), patch.dict(
                    os.environ, {"CAPIVARA_YARAX_BIN": "", "CAPIVARA_YARAX_RULES_PATH": ""}, clear=False
                ):
                    status = module.scanner_status()
                self.assertFalse(status["ready"])
                self.assertEqual(status["state"], "missing_engine")
                self.assertEqual(status["engine_state"], "missing")
                self.assertIn("engine is unavailable", status["last_error"])

    def test_ready_managed_state_exposes_versions_checksum_and_count(self):
        for platform_name in ("linux", "windows"):
            with self.subTest(platform=platform_name):
                module = self._scanner(platform_name)
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    binary = root / ("yr.exe" if platform_name == "windows" else "yr")
                    binary.write_bytes(b"x")
                    rules = root / "baseline.yar"
                    rules.write_text("rule baseline { condition: false }\n", encoding="utf-8")
                    engine_status = {
                        "state": "ready",
                        "managed": True,
                        "installed_version": "1.20.0",
                        "pinned_version": "1.20.0",
                        "error": None,
                    }
                    rules_status = {
                        "state": "ready",
                        "managed": True,
                        "ruleset_version": "2026.09.18.1",
                        "pinned_ruleset_version": "2026.09.18.1",
                        "sha256": "abc",
                        "expected_sha256": "abc",
                        "checksum_valid": True,
                    }
                    with patch.object(module, "_managed_engine_status", return_value=engine_status), patch.object(
                        module, "_managed_rules_status", return_value=rules_status
                    ), patch.object(module, "_managed_yarax_binary", return_value=str(binary)), patch.object(
                        module, "_managed_yarax_rules_path", return_value=str(rules)
                    ), patch.dict(os.environ, {"CAPIVARA_YARAX_BIN": "", "CAPIVARA_YARAX_RULES_PATH": ""}, clear=False):
                        status = module.scanner_status()
                    self.assertTrue(status["ready"])
                    self.assertEqual(status["state"], "ready")
                    self.assertEqual(status["engine_version"], "1.20.0")
                    self.assertEqual(status["ruleset_version"], "2026.09.18.1")
                    self.assertEqual(status["rules_count"], 1)
                    self.assertTrue(status["ruleset_checksum_valid"])
                    self.assertTrue(status["engine_managed"])
                    self.assertTrue(status["rules_managed"])
                    self.assertIsNone(status["last_error"])

    def test_broken_managed_rules_fail_closed_without_legacy_fallback(self):
        for platform_name in ("linux", "windows"):
            with self.subTest(platform=platform_name):
                module = self._scanner(platform_name)
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    binary = root / ("yr.exe" if platform_name == "windows" else "yr")
                    binary.write_bytes(b"x")
                    legacy = root / "legacy"
                    legacy.mkdir()
                    (legacy / "legacy.yar").write_text("rule legacy { condition: false }\n", encoding="utf-8")
                    with patch.object(
                        module, "_managed_engine_status",
                        return_value={"state": "ready", "managed": True, "installed_version": "1.20.0"},
                    ), patch.object(
                        module, "_managed_rules_status",
                        return_value={
                            "state": "error",
                            "managed": True,
                            "ruleset_version": "2026.09.18.1",
                            "checksum_valid": False,
                            "error": "Managed YARA-X ruleset metadata or checksum is invalid",
                        },
                    ), patch.object(module, "_managed_yarax_binary", return_value=str(binary)), patch.object(
                        module, "_managed_yarax_rules_path", return_value=None
                    ), patch.object(module, "LEGACY_RULES_PATH", legacy), patch.dict(
                        os.environ, {"CAPIVARA_YARAX_BIN": "", "CAPIVARA_YARAX_RULES_PATH": ""}, clear=False
                    ):
                        status = module.scanner_status()
                        selected = module._rules_path()
                    self.assertFalse(status["ready"])
                    self.assertEqual(status["state"], "rules_error")
                    self.assertTrue(status["rules_managed"])
                    self.assertFalse(status["ruleset_checksum_valid"])
                    self.assertIn(".invalid-managed-ruleset", str(selected))
                    self.assertIn("checksum", status["last_error"])

    def test_broken_managed_engine_does_not_fall_back_to_system_yr(self):
        module = self._scanner("linux")
        with patch.object(
            module, "_managed_engine_status",
            return_value={"state": "error", "managed": True, "error": "managed binary unavailable"},
        ), patch.object(module, "_managed_yarax_binary", return_value=None), patch.object(
            module.shutil, "which", return_value="/usr/bin/yr"
        ), patch.dict(os.environ, {"CAPIVARA_YARAX_BIN": ""}, clear=False):
            self.assertIsNone(module._binary())

    def test_linux_doctor_emits_yarax_findings_and_security_payload(self):
        module = load_runtime("linux", "local_cli.py", f"y3_linux_doctor_{id(self)}")
        base_capabilities = {
            "content_security": {
                "ready": False,
                "state": "rules_error",
                "engine_state": "ready",
                "rules_state": "error",
                "ruleset_checksum_valid": False,
                "last_error": "YARA-X ruleset validation/checksum failed.",
            },
            "steamcmd_status": {"installed": False},
        }
        config = {"agent_id": "a", "node_id": "n"}
        with patch.object(module, "_identity", return_value={"agent_id": "a", "node_id": "n", "enrolled": True}), patch.object(
            module, "_service_state", return_value={"healthy": True}
        ), patch.object(
            module, "_heartbeat", return_value={"controller": {"reachable": True}}
        ), patch.object(module, "detect_capabilities", return_value=base_capabilities), patch.object(
            module, "_ports", return_value={"configured": True, "conflict_count": 0}
        ), patch.object(
            module, "_host", return_value={"storage_root_free_bytes": 10 * 1024**3}
        ), patch.object(
            module, "game_data_summary", return_value={"failed_recent_jobs": 0}
        ), patch.object(module, "update_status", return_value={}):
            result = module._doctor(config)
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("yarax_rules_invalid", codes)
        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["security"]["content"]["ready"])

    def test_windows_doctor_exposes_equivalent_yarax_findings(self):
        module = load_runtime("windows", "admin_gui_backend.py", f"y3_windows_doctor_{id(self)}")
        capabilities = {
            "content_security": {
                "ready": False,
                "state": "missing_engine",
                "engine_state": "missing",
                "rules_state": "missing",
                "last_error": "YARA-X engine is unavailable",
            }
        }
        with patch.object(module, "detect_capabilities", return_value=capabilities):
            result = module._security_health()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["findings"][0]["code"], "yarax_engine_missing")
        self.assertEqual(result["content_security"]["state"], "missing_engine")

    def test_capabilities_contract_includes_enriched_content_security(self):
        for platform_name in ("linux", "windows"):
            source = (ROOT / "agents" / platform_name / "runtime" / "capabilities.py").read_text(encoding="utf-8")
            self.assertRegex(source, r'"content_security"\s*:\s*content_security')
        source = (ROOT / "agents" / "linux" / "runtime" / "content_security.py").read_text(encoding="utf-8")
        for key in ("engine_version", "ruleset_version", "rules_count", "ruleset_checksum_valid", "last_error"):
            self.assertIn(f'"{key}"', source)


class HybridYaraXStateOwnershipTest(unittest.TestCase):
    def test_dashboard_worker_uses_bounded_yarax_state_bootstrap_helper(self):
        unit = (ROOT / "systemd" / "dsm-dashboard-worker.service").read_text(encoding="utf-8")
        helper = ROOT / "dashboard" / "workers" / "prepare_hybrid_yarax_state.py"
        self.assertTrue(helper.is_file())
        exec_line = (
            "ExecStartPre=+/usr/bin/python3 /opt/dsm/dashboard/workers/"
            "prepare_hybrid_yarax_state.py --root /opt/dsm "
            "--user {{DSM_USER}} --group {{DSM_GROUP}}"
        )
        self.assertIn(exec_line, unit)
        self.assertLess(unit.index(exec_line), unit.index("ExecStart=/bin/bash"))
        self.assertNotIn("chown -R", unit)

    def test_yarax_state_bootstrap_helper_is_bounded(self):
        source = (ROOT / "dashboard" / "workers" / "prepare_hybrid_yarax_state.py").read_text(encoding="utf-8")
        self.assertIn('"runtime" / "hybrid-agent-state" / "security" / "yara-x"', source)
        self.assertIn("target.relative_to(root)", source)
        self.assertIn("followlinks=False", source)
        self.assertIn("follow_symlinks=False", source)




if __name__ == "__main__":
    unittest.main()
