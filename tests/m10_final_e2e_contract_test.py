#!/usr/bin/env python3
from __future__ import annotations
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class M10FinalE2EContractTest(unittest.TestCase):
    def test_required_harnesses_exist(self):
        required=[
            "tests/universal_content_e2e_test.py",
            "tests/maintenance_controller_agent_e2e.py",
            "tests/dayz_native_restart_transport_test.py",
            "tests/dayz_native_restart_agent_parity_test.py",
            "tests/dayz_native_maintenance_worker_test.py",
            "tests/m7_maintenance_framework_regression_test.py",
            "tests/m7_minecraft_java_windows_maintenance_test.py",
            "tests/m9_modpack_bundle_read_model_test.py",
            "tests/baseline_release_upgrade_contract_test.py",
            "tests/baseline_v12_v13_registry_test.py",
            "tests/update_baseline_upgrade_path_test.py",
            "tests/release_readiness_test.py",
        ]
        for path in required:
            with self.subTest(path=path):
                self.assertTrue((ROOT/path).is_file(),path)

    def test_ucp_e2e_keeps_required_representative_matrix(self):
        source=(ROOT/"tests"/"universal_content_e2e_test.py").read_text(encoding="utf-8")
        for token in (
            "paper_order",
            "neo_order",
            "pack_revision",
            "blocked_state",
            "isolation",
            "CAPIVARA_U10_PLATFORM",
            "dayz",
            "projectzomboid",
        ):
            self.assertIn(token,source)

    def test_maintenance_e2e_is_real_controller_agent_transport(self):
        source=(ROOT/"tests"/"maintenance_controller_agent_e2e.py").read_text(encoding="utf-8")
        for token in (
            "ControllerHandler",
            "linux_agent.enroll",
            "linux_agent.heartbeat",
            "MaintenanceWorker",
            "AgentInstanceRuntimeRepository",
            '"status", "stop", "start", "doctor"',
        ):
            self.assertIn(token,source)

    def test_final_workflow_requires_linux_and_windows_before_gate(self):
        workflow=(ROOT/".github"/"workflows"/"m10-final-e2e-release.yml").read_text(encoding="utf-8")
        for token in (
            "linux-final-e2e:",
            "windows-final-e2e:",
            "needs: [linux-final-e2e, windows-final-e2e]",
            "baseline_release_upgrade_contract_test.py",
            "update_baseline_upgrade_path_test.py",
            "release_readiness_test.py",
        ):
            self.assertIn(token,workflow)

if __name__=="__main__":
    unittest.main()
