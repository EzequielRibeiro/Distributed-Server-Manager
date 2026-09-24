#!/usr/bin/env python3
from __future__ import annotations
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CustomerDayZManagementContractTest(unittest.TestCase):
 def test_customer_surface_is_composed(self):
  html=(ROOT/"dashboard"/"web"/"customer-instance.html").read_text(encoding="utf-8")
  self.assertIn("/customer-maintenance.js?v=3",html)
  self.assertIn("/customer-dayz.js?v=5",html)
  layer=(ROOT/"dashboard"/"server_part20.py").read_text(encoding="utf-8")
  self.assertIn("install_customer_dayz_http",layer)
  self.assertIn('"/customer-dayz.js"',layer)
  self.assertIn('"/customer-maintenance.js"',layer)
  dayz_js=(ROOT/"dashboard"/"web"/"customer-dayz.js").read_text(encoding="utf-8")
  self.assertIn('scope.append(new Option("Persistência do mapa atual","persistence"),new Option("Persistência + perfis","persistence-and-profiles"))',dayz_js)
  self.assertNotIn('scope.add(new Option("Persistência do mapa atual","persistence"),new Option("Persistência + perfis","persistence-and-profiles"))',dayz_js)
  self.assertIn('"Abrir Conteúdo"',dayz_js)
  self.assertIn('"comunitário"',dayz_js)
  self.assertIn("m.can_activate",dayz_js)
  self.assertIn("mapSelection",dayz_js)
  self.assertIn("remembered=missions.find",dayz_js)
  self.assertIn("blockingOperation",dayz_js)
  self.assertIn("Falha ao solicitar troca:",dayz_js)
  self.assertIn("dayz-map-content-mode",dayz_js)
  self.assertIn("Iniciar novo mapa com mods desabilitados (recomendado)",dayz_js)
  self.assertIn("Manter mods ativos (preflight de compatibilidade)",dayz_js)
  self.assertIn("content_mode:mapContentMode",dayz_js)
 def test_dayz_api_supports_map_and_scheduled_wipe(self):
  source=(ROOT/"dashboard"/"customer_dayz_http.py").read_text(encoding="utf-8")
  for token in ('"refresh_maps"','"change_mission"','"wipe"','"cancel"',"scheduled_at"):
   self.assertIn(token,source)
  self.assertIn("DISCOVERY_SCHEMA_VERSION=2",source)
  self.assertIn("_discovery_payload",source)
  self.assertIn('"content_mode":content_mode',source)
  self.assertIn('content_mode not in {"disable","keep"}',source)
  self.assertIn("stale_after_change",source)
  self.assertIn('op.get("action")=="change_mission" and op.get("status")=="completed"',source)
  for platform in ("linux","windows"):
   operation=(ROOT/"agents"/platform/"runtime"/"dayz_operation_client.py").read_text(encoding="utf-8")
   runtime=(ROOT/"agents"/platform/"runtime"/"content_activation_runtime.py").read_text(encoding="utf-8")
   projection=(ROOT/"agents"/platform/"runtime"/"content_activation_projection.py").read_text(encoding="utf-8")
   self.assertIn("mod_compatibility_preflight",operation)
   self.assertIn('payload.get("content_mode") or "disable"',operation)
   self.assertIn("activation_snapshot(iid)",operation)
   self.assertIn("project_runtime_spec(updated,snapshot)",operation)
   self.assertIn("dayz_content_enabled",runtime)
   self.assertIn("dayz_map_compatibility",projection)
 def test_upgrade_is_registered(self):
  source=(ROOT/"database"/"baseline_upgrade_engine.py").read_text(encoding="utf-8")
  self.assertIn('BaselineUpgrade(21, "dayz_management_operations"',source)
  schema=(ROOT/"database"/"schema_baseline.py").read_text(encoding="utf-8")
  self.assertIn("ensure_dayz_management_schema",schema)

if __name__=="__main__":unittest.main()
