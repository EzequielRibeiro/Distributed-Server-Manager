#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_ssh_deploy import AgentDeployError, SSHDeployOptions, SSHResult, bootstrap_agent


class AgentSSHBootstrapDiagnosticTest(unittest.TestCase):
    def test_bootstrap_error_marker_beats_success_stdout(self):
        def runner(argv, stdin_text, timeout):
            return SSHResult(
                1,
                "[Capivara Agent] Baixando pacote Linux Agent de GitHub Release...\n"
                "[Capivara Agent] Pacote validado por SHA-256.\n",
                "[Capivara Agent][ERRO] arquivo obrigatório ausente: agent/runtime/example.py\n"
                "CAPIVARA_BOOTSTRAP_ERROR: Agent installer exited with status 1\n",
            )

        with self.assertRaises(AgentDeployError) as ctx:
            bootstrap_agent(
                SSHDeployOptions(host="192.168.15.59", ssh_user="mine"),
                controller_url="https://controller.example:9443",
                pairing_token="secret-not-for-output",
                runner=runner,
            )

        message = str(ctx.exception)
        self.assertIn("CAPIVARA_BOOTSTRAP_ERROR: Agent installer exited with status 1", message)
        self.assertNotIn("Pacote validado por SHA-256", message)
        self.assertNotIn("secret-not-for-output", message)

    def test_agent_error_marker_beats_success_stdout_when_wrapper_marker_absent(self):
        def runner(argv, stdin_text, timeout):
            return SSHResult(
                1,
                "[Capivara Agent] Pacote validado por SHA-256.\n",
                "[Capivara Agent][ERRO] Controller enrollment recusado\n",
            )

        with self.assertRaises(AgentDeployError) as ctx:
            bootstrap_agent(
                SSHDeployOptions(host="192.168.15.59", ssh_user="mine"),
                controller_url="https://controller.example:9443",
                pairing_token="secret-not-for-output",
                runner=runner,
            )

        self.assertIn("[Capivara Agent][ERRO] Controller enrollment recusado", str(ctx.exception))
        self.assertNotIn("Pacote validado por SHA-256", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
