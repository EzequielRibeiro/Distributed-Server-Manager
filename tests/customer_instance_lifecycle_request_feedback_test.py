#!/usr/bin/env python3
"""Customer lifecycle controls must surface rejected requests rather than fail silently."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "dashboard" / "web" / "customer-instance-v2.js").read_text(encoding="utf-8")
SERVICE = (ROOT / "dashboard" / "customer_instance_workspace_service.py").read_text(encoding="utf-8")


class CustomerLifecycleFeedbackContractTest(unittest.TestCase):
    def test_restart_failure_is_reported_to_customer(self):
        self.assertIn('control("restart").catch(error=>toast(`Falha ao reiniciar: ${error.message}`))', JS)
        self.assertIn('control("start").catch(error=>toast(`Falha ao iniciar: ${error.message}`))', JS)
        self.assertIn('control("stop").catch(error=>toast(`Falha ao parar: ${error.message}`))', JS)

    def test_control_uses_authoritative_node_and_game_identity(self):
        self.assertIn('registered=overview?.instance||{}', JS)
        self.assertIn('registered.node_id||q.get("server")', JS)
        self.assertIn('registered.game_id||q.get("game")', JS)
        self.assertIn('if(!server||!game||!iid)throw new Error(', JS)
        self.assertIn('"node_id","game_id"', SERVICE)

    def test_success_is_reported_only_after_request_returns(self):
        request = JS.index('const result=await request(`/api/instance/${action}`')
        guard = JS.index('if(result?.ok===false)throw new Error(', request)
        toast = JS.index('toast(`Comando ${action} concluído pelo Agent.`)', guard)
        self.assertLess(request, guard)
        self.assertLess(guard, toast)
        self.assertIn('await loadOverview();return result', JS)


if __name__ == "__main__":
    unittest.main()
