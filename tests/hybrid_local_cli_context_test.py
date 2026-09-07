#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "agents" / "linux" / "runtime" / "cap_dispatch.py"


class HybridLocalCliContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "agents" / "linux" / "runtime"
        self.state = self.root / "runtime" / "hybrid-agent-state"
        self.config_dir = self.root / "config"
        self.runtime.mkdir(parents=True)
        self.state.mkdir(parents=True)
        self.config_dir.mkdir(parents=True)
        shutil.copy2(DISPATCH, self.runtime / "cap_dispatch.py")
        (self.state / "agent.json").write_text(
            json.dumps({"agent_id": "hybrid-agent"}),
            encoding="utf-8",
        )
        (self.config_dir / "agent.conf").write_text(
            'AGENT_ID="hybrid-agent"\n'
            'AGENT_NAME="Hybrid Test"\n'
            'DSM_NODE_ID="hybrid-node"\n'
            'DSM_NODE_ROLE="hybrid"\n',
            encoding="utf-8",
        )
        (self.runtime / "controller_cli.py").write_text(
            "def main(args=None):\n    return 0\n",
            encoding="utf-8",
        )
        (self.runtime / "local_cli.py").write_text(
            "import json, os\n"
            "def _doctor(config):\n"
            "    return {\n"
            "        'status': 'critical', 'ready': False,\n"
            "        'identity': {'agent_id': config.get('agent_id'), 'node_id': None, 'enrolled': False},\n"
            "        'service': {'service': os.environ.get('CAPIVARA_AGENT_SERVICE'), 'healthy': True},\n"
            "        'heartbeat': {'controller': {'configured': False, 'reachable': False}},\n"
            "        'findings': [\n"
            "            {'code': 'identity_incomplete', 'severity': 'critical', 'message': 'standalone'},\n"
            "            {'code': 'not_enrolled', 'severity': 'critical', 'message': 'standalone'},\n"
            "            {'code': 'service_inactive', 'severity': 'critical', 'message': 'standalone'},\n"
            "            {'code': 'controller_unreachable', 'severity': 'warning', 'message': 'standalone'},\n"
            "            {'code': 'steamcmd_not_functional', 'severity': 'warning', 'message': 'real warning'},\n"
            "        ],\n"
            "    }\n"
            "def main(args=None):\n"
            "    print(json.dumps({\n"
            "        'root': os.environ.get('CAPIVARA_AGENT_ROOT'),\n"
            "        'state': os.environ.get('CAPIVARA_AGENT_STATE_DIR'),\n"
            "        'config': os.environ.get('CAPIVARA_AGENT_CONFIG'),\n"
            "    }))\n"
            "    return 0\n",
            encoding="utf-8",
        )
        (self.runtime / "instance_runtime.py").write_text(
            "import os\n"
            "def lifecycle(config, instance_id, action):\n"
            "    return {\n"
            "        'agent_id': config.get('agent_id'),\n"
            "        'instance_id': instance_id,\n"
            "        'action': action,\n"
            "        'state': os.environ.get('CAPIVARA_AGENT_STATE_DIR'),\n"
            "        'config_path': os.environ.get('CAPIVARA_AGENT_CONFIG'),\n"
            "    }\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in (
            "CAPIVARA_AGENT_ROOT",
            "CAPIVARA_AGENT_STATE_DIR",
            "CAPIVARA_AGENT_CONFIG",
            "CAPIVARA_AGENT_MODE",
            "CAPIVARA_AGENT_SERVICE",
            "CAPIVARA_DSM_ROOT",
        ):
            env.pop(key, None)
        return env

    def _run(self, *args: str, env: dict[str, str] | None = None) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(self.runtime / "cap_dispatch.py"), *args],
            env=env or self._env(),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def _assert_hybrid_doctor(self, payload: dict[str, object]) -> None:
        self.assertEqual(payload["mode"], "hybrid")
        identity = payload["identity"]
        self.assertEqual(identity["agent_id"], "hybrid-agent")
        self.assertEqual(identity["node_id"], "hybrid-node")
        self.assertEqual(identity["credential_type"], "embedded-database")
        self.assertTrue(identity["enrolled"])
        heartbeat = payload["heartbeat"]
        self.assertEqual(heartbeat["controller"]["transport"], "embedded-database")
        self.assertTrue(heartbeat["controller"]["reachable"])
        self.assertEqual(payload["service"]["service"], "dsm-dashboard-worker.service")
        codes = {item["code"] for item in payload["findings"]}
        self.assertNotIn("identity_incomplete", codes)
        self.assertNotIn("not_enrolled", codes)
        self.assertNotIn("service_inactive", codes)
        self.assertNotIn("controller_unreachable", codes)
        self.assertIn("steamcmd_not_functional", codes)
        self.assertEqual(payload["status"], "degraded")
        self.assertTrue(payload["ready"])

    def test_agent_cli_uses_embedded_hybrid_paths(self) -> None:
        payload = self._run("agent", "status", "--json")
        self.assertEqual(payload["root"], str(self.root / "agents" / "linux"))
        self.assertEqual(payload["state"], str(self.state))
        self.assertEqual(payload["config"], str(self.state / "agent.json"))

    def test_instance_lifecycle_reads_hybrid_config_and_state(self) -> None:
        payload = self._run("instance", "start", "instance-01", "--json")
        self.assertEqual(payload["agent_id"], "hybrid-agent")
        self.assertEqual(payload["instance_id"], "instance-01")
        self.assertEqual(payload["action"], "start")
        self.assertEqual(payload["state"], str(self.state))
        self.assertEqual(payload["config_path"], str(self.state / "agent.json"))

    def test_hybrid_doctor_uses_embedded_identity_and_service_contract(self) -> None:
        self._assert_hybrid_doctor(self._run("agent", "doctor", "--json"))

    def test_canonical_cap_forwarded_doctor_uses_hybrid_contract(self) -> None:
        # bin/cap strips the leading `agent` token before invoking cap_dispatch.py.
        self._assert_hybrid_doctor(self._run("doctor", "--json"))

    def test_explicit_agent_context_overrides_embedded_defaults(self) -> None:
        override_root = self.root / "override-agent"
        override_state = self.root / "override-state"
        override_config = self.root / "override.json"
        override_config.write_text("{}", encoding="utf-8")
        env = self._env()
        env.update(
            {
                "CAPIVARA_AGENT_ROOT": str(override_root),
                "CAPIVARA_AGENT_STATE_DIR": str(override_state),
                "CAPIVARA_AGENT_CONFIG": str(override_config),
            }
        )
        payload = self._run("agent", "status", "--json", env=env)
        self.assertEqual(payload["root"], str(override_root))
        self.assertEqual(payload["state"], str(override_state))
        self.assertEqual(payload["config"], str(override_config))


if __name__ == "__main__":
    unittest.main()
