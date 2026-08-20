#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentDashboardUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "dashboard/web/agents.html").read_text(encoding="utf-8")
        cls.install = (ROOT / "dashboard/web/agent-installation.js").read_text(encoding="utf-8")
        cls.location = (ROOT / "dashboard/web/agent-location-ui.js").read_text(encoding="utf-8")
        cls.updates = (ROOT / "dashboard/web/agent-updates.js").read_text(encoding="utf-8")
        cls.service = (ROOT / "systemd/dsm-dashboard.service").read_text(encoding="utf-8")

    def test_add_agent_controls_are_present(self):
        for text in ("Adicionar Agent", "Linux", "Windows", "GitHub Release", "Pacote local", "Região", "Datacenter", "Gerar instalação"):
            self.assertIn(text, self.html)

    def test_installation_progress_states_are_present(self):
        for text in ("Aguardando Agent", "Pareando", "Validando", "Online"):
            self.assertIn(text, self.html)
        self.assertIn("/agents/installations", self.install)
        self.assertIn("/agents/installations/status", self.install)

    def test_location_controls_include_region_and_safety_message(self):
        self.assertIn('id="agent-region"', self.html)
        self.assertIn('id="agent-datacenter"', self.html)
        self.assertIn('id="agent-public-host"', self.html)
        self.assertIn('id="agent-latitude"', self.html)
        self.assertIn('id="agent-longitude"', self.html)
        self.assertIn("Instâncias existentes permanecem vinculadas ao Agent", self.html)
        self.assertIn("region_id", self.location)

    def test_remote_update_controls_and_batch_contract_are_present(self):
        for text in ("Versão instalada", "Versão disponível", "Tamanho do lote", "Stable", "Beta", "Local / manual"):
            self.assertIn(text, self.html)
        self.assertIn("/agents/updates/rollouts", self.updates)
        self.assertIn("/agents/updates/status", self.updates)
        self.assertIn("batch_size", self.updates)

    def test_phase_assets_and_current_entrypoint_are_loaded(self):
        self.assertIn('/agent-installation.js', self.html)
        self.assertIn('/agent-location-ui.js', self.html)
        self.assertIn('/agent-updates.js', self.html)
        self.assertIn('dashboard/server_part13.py', self.service)


if __name__ == "__main__":
    unittest.main()
