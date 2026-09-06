#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core.agent_eligibility import evaluate_agent_eligibility
from core.placement_requirements import PlacementRequirements,requirements_from_runtime_definition

class RuntimeProfilePlacementParityTest(unittest.TestCase):
 def _runtime(self,profiles,os_name="linux"):
  return {"status":"active","health_status":"online","capabilities":{"platform":{"os":os_name,"architecture":"x86_64"},"runtime_profiles":profiles,"native-linux":os_name=="linux","native-windows":os_name=="windows","steamcmd":True,"java":True,"java_status":{"major":21}}}
 def _evaluate(self,runtime,environment_id):
  requirements=PlacementRequirements(environment_id=environment_id)
  return evaluate_agent_eligibility(runtime=runtime,port_summary={"ranges":[]},requirements=requirements)
 def test_exact_environment_profile_is_required(self):
  self.assertTrue(self._evaluate(self._runtime(["dayz","dayz.stable"]),"dayz.stable").eligible)
  result=self._evaluate(self._runtime(["dayz","dayz.stable"]),"rust.stable")
  self.assertFalse(result.eligible);self.assertIn("unsupported_runtime_profile",result.reasons)
 def test_legacy_heartbeat_without_profiles_fails_closed_for_canonical_runtime(self):
  runtime=self._runtime(["dayz.stable"]);runtime["capabilities"].pop("runtime_profiles")
  result=self._evaluate(runtime,"dayz.stable")
  self.assertFalse(result.eligible);self.assertIn("runtime_profiles_missing",result.reasons)
 def test_no_environment_requirement_keeps_legacy_generic_placement_compatible(self):
  runtime={"status":"active","health_status":"online","capabilities":{"java":True}}
  result=evaluate_agent_eligibility(runtime=runtime,port_summary={"ranges":[]},requirements=PlacementRequirements(capabilities=frozenset({"java"})))
  self.assertTrue(result.eligible,result.reasons)
 def test_runtime_definition_carries_its_canonical_id(self):
  result=requirements_from_runtime_definition({"kind":"RuntimeDefinition","id":"DayZ.Stable","game":"DayZ","process":{"engine":"native"},"requirements":{"os":["linux","windows"]}})
  self.assertEqual(result.environment_id,"dayz.stable")
 def test_windows_dayz_does_not_satisfy_rust_or_minecraft(self):
  runtime=self._runtime(["dayz","dayz.stable"],os_name="windows")
  for requested in ("rust.stable","minecraft.java.vanilla","mindustry.github"):
   with self.subTest(requested=requested):self.assertIn("unsupported_runtime_profile",self._evaluate(runtime,requested).reasons)

if __name__=="__main__":unittest.main()
