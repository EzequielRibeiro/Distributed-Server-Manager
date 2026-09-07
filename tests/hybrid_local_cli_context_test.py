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
        self.runtime.mkdir(parents=True)
        self.state.mkdir(parents=True)
        shutil.copy2(DISPATCH, self.runtime / "cap_dispatch.py")
        (self.state / "agent.json").write_text(
            json.dumps({"agent_id": "hybrid-agent", "node_id": "hybrid-node"}),
            encoding="utf-8",
        )
        (self.runtime / "controller_cli.py").write_text(
            "def main(args=None):\n    return 0\n",
            encoding="utf-8",
        )
        (self.runtime / "local_cli.py").write_text(
            "import json, os\n"
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
