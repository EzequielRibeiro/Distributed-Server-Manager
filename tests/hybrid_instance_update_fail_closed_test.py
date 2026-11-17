#!/usr/bin/env python3
"""Regression: Hybrid must not send instance updates to generic install-json."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXECUTOR = Path(__file__).resolve().parents[1] / "dashboard/workers/hybrid_game_data_executor.py"


class HybridInstanceUpdateFailClosedTest(unittest.TestCase):
    def test_instance_update_does_not_invoke_generic_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            result = root / "result.json"
            request.write_text(json.dumps({
                "job_id": "test-instance-update",
                "action": "update",
                "selection": {
                    "kind": "RuntimeSelection",
                    "game": "dayz",
                    "provider": "steam",
                    "install_dir": str(root / "incorrect-generic-target"),
                    "_server_update": {
                        "operation": "update",
                        "instance_id": "cli-000001-dayz-001",
                        "backup_before_update": True,
                    },
                },
            }), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(EXECUTOR), str(root), str(request), str(result)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["error"], "hybrid_instance_update_transaction_unavailable")
            self.assertFalse((root / "incorrect-generic-target").exists())


    def test_nonzero_agent_exit_never_publishes_completed_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent_executor = root / "agents/linux/runtime/game_data_executor.py"
            agent_executor.parent.mkdir(parents=True)
            agent_executor.write_text(
                "import json,sys\n"
                "from pathlib import Path\n"
                "job=json.loads(Path(sys.argv[1]).read_text())['job_id']\n"
                "Path(sys.argv[2]).write_text(json.dumps({'job_id':job,'status':'completed'}))\n"
                "sys.exit(1)\n",
                encoding="utf-8",
            )
            request = root / "request.json"
            result = root / "result.json"
            request.write_text(json.dumps({
                "job_id": "test-agent-nonzero",
                "action": "update",
                "selection": {
                    "game": "dayz", "provider": "steam",
                    "_server_update": {"instance_id": "dayz-001", "operation": "update"},
                },
            }), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(EXECUTOR), str(root), str(request), str(result)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["error"], "hybrid_instance_update_transaction_failed")

    def test_transactional_executor_receives_hybrid_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent_executor = root / "agents/linux/runtime/game_data_executor.py"
            agent_executor.parent.mkdir(parents=True)
            agent_executor.write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "payload = {\n"
                "  'job_id': json.loads(Path(sys.argv[1]).read_text())['job_id'],\n"
                "  'status': 'completed',\n"
                "  'agent_state': os.environ.get('CAPIVARA_AGENT_STATE_DIR'),\n"
                "  'agent_config': os.environ.get('CAPIVARA_AGENT_CONFIG'),\n"
                "}\n"
                "Path(sys.argv[2]).write_text(json.dumps(payload))\n",
                encoding="utf-8",
            )
            request = root / "request.json"
            result = root / "result.json"
            request.write_text(json.dumps({
                "job_id": "test-transactional-routing",
                "action": "update",
                "selection": {
                    "game": "dayz", "provider": "steam",
                    "_server_update": {"instance_id": "cli-000001-dayz-001", "operation": "update"},
                },
            }), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(EXECUTOR), str(root), str(request), str(result)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["agent_state"], str(root / "runtime/hybrid-agent-state"))
            self.assertEqual(payload["agent_config"], str(root / "runtime/hybrid-agent-state/agent.json"))
            # A scoped version check must use the same registered-instance
            # executor, never the generic install_dir Steam probe.
            request.write_text(json.dumps({
                "job_id": "test-scoped-version-check",
                "action": "verify",
                "selection": {
                    "game": "dayz", "provider": "steam",
                    "install_dir": str(root / "incorrect-generic-target"),
                    "_server_update": {"instance_id": "cli-000001-dayz-001", "operation": "check"},
                },
            }), encoding="utf-8")
            result.unlink()
            check = subprocess.run(
                [sys.executable, str(EXECUTOR), str(root), str(request), str(result)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            checked = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(checked["job_id"], "test-scoped-version-check")
            self.assertEqual(checked["agent_state"], str(root / "runtime/hybrid-agent-state"))
            self.assertFalse((root / "incorrect-generic-target").exists())


if __name__ == "__main__":
    unittest.main()
