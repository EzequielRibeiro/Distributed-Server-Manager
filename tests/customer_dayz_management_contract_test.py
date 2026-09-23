#!/usr/bin/env python3
from __future__ import annotations
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CustomerDayZManagementContractTest(unittest.TestCase):
 def test_customer_surface_is_composed(self):
  html=(ROOT/"dashboard"/"web"/"customer-instance.html").read_text(encoding="utf-8")
  self.assertIn("/customer-maintenance.js?v=2",html)
  self.assertIn("/customer-dayz.js?v=1",html)
  layer=(ROOT/"dashboard"/"server_part20.py").read_text(encoding="utf-8")
  self.assertIn("install_customer_dayz_http",layer)
  self.assertIn('"/customer-dayz.js"',layer)
  self.assertIn('"/customer-maintenance.js"',layer)
  dayz_js=(ROOT/"dashboard"/"web"/"customer-dayz.js").read_text(encoding="utf-8")
  self.assertIn('scope.append(new Option("Persistência do mapa atual","persistence"),new Option("Persistência + perfis","persistence-and-profiles"))',dayz_js)
  self.assertNotIn('scope.add(new Option("Persistência do mapa atual","persistence"),new Option("Persistência + perfis","persistence-and-profiles"))',dayz_js)
  self.assertIn("nativePickerActive",dayz_js)
  self.assertIn("!nativePickerActive&&!editing",dayz_js)
  maintenance_js=(ROOT/"dashboard"/"web"/"customer-maintenance.js").read_text(encoding="utf-8")
  self.assertIn('button.addEventListener("click",setActive)',maintenance_js)
  self.assertNotIn("button.onclick=setActive",maintenance_js)
 def test_dayz_api_supports_map_and_scheduled_wipe(self):
  source=(ROOT/"dashboard"/"customer_dayz_http.py").read_text(encoding="utf-8")
  for token in ('"refresh_maps"','"change_mission"','"wipe"','"cancel"',"scheduled_at"):
   self.assertIn(token,source)
 def test_upgrade_is_registered(self):
  source=(ROOT/"database"/"baseline_upgrade_engine.py").read_text(encoding="utf-8")
  self.assertIn('BaselineUpgrade(21, "dayz_management_operations"',source)
  schema=(ROOT/"database"/"schema_baseline.py").read_text(encoding="utf-8")
  self.assertIn("ensure_dayz_management_schema",schema)

if __name__=="__main__":unittest.main()
