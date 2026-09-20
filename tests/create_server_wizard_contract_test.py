#!/usr/bin/env python3
from __future__ import annotations
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CreateServerWizardContractTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.script=(ROOT/"dashboard/web/create-server-wizard.js").read_text(encoding="utf-8");cls.css=(ROOT/"dashboard/web/create-server-wizard.css").read_text(encoding="utf-8");cls.html=(ROOT/"dashboard/web/customer.html").read_text(encoding="utf-8");cls.service=(ROOT/"systemd/dsm-dashboard.service").read_text(encoding="utf-8")
 def test_all_required_states_are_present(self):
  for label in ("Verificando ambientes...","Ambiente disponível","Nenhum ambiente disponível","Criando servidor...","Provisionando...","Concluído","Falha"):self.assertIn(label,self.script)
 def test_unavailable_message_is_explicit(self):self.assertIn("Nenhum ambiente está disponível para provisionamento neste momento.",self.script);self.assertIn("/api/placement/readiness",self.script)
 def test_opening_cta_is_hidden_while_wizard_is_open(self):self.assertIn("setOpeningCtasHidden(true)",self.script);self.assertIn("setOpeningCtasHidden(false)",self.script);self.assertIn("create-instance-submit",self.script)
 def test_fallback_summary_follows_checkbox(self):self.assertIn("runtime-region-fallback",self.script);self.assertIn('checkbox.checked ? "Sim" : "Não"',self.script)
 def test_phase7_assets_are_loaded(self):self.assertIn('/create-server-wizard.css?v=4',self.html);self.assertIn('/create-server-wizard.js?v=4',self.html);self.assertIn('id="runtime-placement-status"',self.html)
 def test_failed_create_surfaces_api_message(self):self.assertIn('data.message||"Não foi possível criar o servidor."',self.script)
 def test_runtime_steps_are_visually_separated(self):self.assertIn(".runtime-step-header",self.css);self.assertIn(".runtime-selector-grid",self.css);self.assertIn(".runtime-selection-summary",self.css)
 def test_submit_observer_is_idempotent(self):self.assertIn("const mustDisable=placementReady===false",self.script);self.assertIn("if(mustDisable&&!submit.disabled)submit.disabled=true",self.script)
 def test_service_uses_current_composed_entrypoint(self):
  self.assertIn("dashboard/server_part22.py",self.service)
  part21=(ROOT/"dashboard/server_part21.py").read_text(encoding="utf-8");self.assertIn("import server_part20 as integration",part21)
  part20=(ROOT/"dashboard/server_part20.py").read_text(encoding="utf-8");self.assertIn("import server_part19 as integration",part20)
  part19=(ROOT/"dashboard/server_part19.py").read_text(encoding="utf-8");self.assertIn("import server_part18 as integration",part19)
  part18=(ROOT/"dashboard/server_part18.py").read_text(encoding="utf-8");self.assertIn("import server_part17 as integration",part18)
  part17=(ROOT/"dashboard/server_part17.py").read_text(encoding="utf-8");self.assertIn("import server_part16 as integration",part17)
if __name__=="__main__":unittest.main()
