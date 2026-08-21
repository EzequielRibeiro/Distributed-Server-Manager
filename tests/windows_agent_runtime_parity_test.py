#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RUNTIME = ROOT / "agents" / "windows" / "runtime"


class WindowsAgentRuntimeParityTest(unittest.TestCase):
    def _run(self, source: str, *, state_dir: str | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(WINDOWS_RUNTIME)
        if state_dir:
            env["CAPIVARA_AGENT_STATE_DIR"] = state_dir
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_instance_command_contract_matches_linux_shape(self):
        with tempfile.TemporaryDirectory() as state:
            result = self._run(
                r'''
                import instance_runtime

                class FakeAdapter:
                    name = "fake"
                    def status(self, instance):
                        return {"available": True, "active_state": "inactive"}
                    def start(self, instance):
                        return {"action": "start", "state": {"available": True, "active_state": "active"}}
                    def stop(self, instance):
                        return {"action": "stop", "state": {"available": True, "active_state": "inactive"}}
                    def restart(self, instance):
                        return {"action": "restart", "state": {"available": True, "active_state": "active"}}
                    def doctor(self, instance):
                        return {"ready": True, "findings": []}

                instance_runtime.resolve_adapter = lambda record: FakeAdapter()
                config = {"agent_id": "win-agent-one"}
                instance_runtime.register_instance({
                    "instance_id": "srv-one",
                    "agent_id": "win-agent-one",
                    "game_id": "generic-game",
                    "runtime_id": "CapivaraInstance-srv-one",
                    "adapter": "fake",
                })
                command = {"command_id": "cmd-start", "instance_id": "srv-one", "action": "start"}
                first = instance_runtime.handle_command(config, command)
                second = instance_runtime.handle_command(config, command)
                assert first == second
                assert first["status"] == "completed"
                assert first["result"]["observed_state"] == "running"
                assert instance_runtime.inventory(config)[0]["instance_id"] == "srv-one"
                assert instance_runtime.read_result()["command_id"] == "cmd-start"
                instance_runtime.clear_result("cmd-start")
                assert instance_runtime.read_result() is None
                ''',
                state_dir=state,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_service_adapter_maps_scm_state(self):
        result = self._run(
            r'''
            from types import SimpleNamespace
            from adapters import windows_service

            def fake_run(*args, **kwargs):
                assert args[:2] == ("query", "CapivaraInstance-srv-one")
                return SimpleNamespace(returncode=0, stdout="STATE              : 4  RUNNING\n", stderr="")

            windows_service._run = fake_run
            adapter = windows_service.WindowsServiceAdapter()
            status = adapter.status({"runtime_id": "CapivaraInstance-srv-one"})
            assert status["available"] is True
            assert status["active_state"] == "active"
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_agent_heartbeat_exposes_instance_contract(self):
        source = (WINDOWS_RUNTIME / "agent.py").read_text(encoding="utf-8")
        self.assertIn('"instances": instance_inventory(config)', source)
        self.assertIn('payload["instance_result"] = instance_result', source)
        self.assertIn('result.get("instance_command")', source)
        self.assertIn("handle_instance_command(config, instance_command)", source)


if __name__ == "__main__":
    unittest.main()
