#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,sys,types,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ContentActivationApplyTest(unittest.TestCase):
 def _module(self,previous,projected):
  calls=[]
  runtime=types.ModuleType("instance_runtime")
  runtime._owned=lambda config,iid:dict(previous)
  runtime.status=lambda config,iid:{"observed_state":"running"}
  runtime.register_instance=lambda spec:calls.append(("register",dict(spec)))
  runtime.lifecycle=lambda config,iid,action:calls.append(("lifecycle",action))
  runtime.doctor=lambda config,iid:{"ready":True}
  privileged=types.ModuleType("privileged_materialization")
  privileged.materialize=lambda config,spec:calls.append(("materialize",dict(spec)))
  projection=types.ModuleType("content_activation_projection")
  projection.activation_snapshot_for_runtime=lambda iid,spec,snapshot:snapshot
  activation=types.ModuleType("content_activation_runtime")
  activation.materialize_content_activation=lambda spec:calls.append(("content_materialize",dict(spec)))
  activation.project_runtime_spec=lambda spec,snapshot:dict(projected)
  saved={name:sys.modules.get(name) for name in ("instance_runtime","privileged_materialization","content_activation_runtime","content_activation_projection")}
  sys.modules.update({"instance_runtime":runtime,"privileged_materialization":privileged,"content_activation_runtime":activation,"content_activation_projection":projection})
  try:
   spec=importlib.util.spec_from_file_location("content_activation_apply_tested",ROOT/"agents/linux/runtime/content_activation_apply.py")
   module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  finally:
   for name,value in saved.items():
    if value is None:sys.modules.pop(name,None)
    else:sys.modules[name]=value
  return module,calls

 def test_dayz_prepared_map_metadata_change_does_not_restart_or_materialize(self):
  previous={"instance_id":"i1","executable":"/srv/dayz","working_directory":"/srv","arguments":["-config=serverDZ.cfg"],"content_activation_checksum":"old","content_dayz_community_missions":[{"id":"empty.deerisle"}]}
  projected={**previous,"content_activation_checksum":"new"}
  projected.pop("content_dayz_community_missions")
  module,calls=self._module(previous,projected)
  result=module.apply_activation_snapshots({},[{"instance_id":"i1","checksum":"new"}])
  self.assertEqual(result,[{"instance_id":"i1","changed":True,"checksum":"new","restarted":False,"metadata_only":True}])
  self.assertEqual([c[0] for c in calls],["register"])

 def test_effective_runtime_argument_change_still_restarts_and_materializes(self):
  previous={"instance_id":"i1","executable":"/srv/dayz","working_directory":"/srv","arguments":["-config=serverDZ.cfg"],"content_activation_checksum":"old"}
  projected={**previous,"arguments":["-config=serverDZ.cfg","-mod=@dsm-i1-123"],"content_activation_checksum":"new"}
  module,calls=self._module(previous,projected)
  result=module.apply_activation_snapshots({},[{"instance_id":"i1","checksum":"new"}])
  self.assertTrue(result[0]["restarted"])
  self.assertEqual([c for c in calls if c[0]=="lifecycle"],[("lifecycle","stop"),("lifecycle","start")])
  self.assertIn("materialize",[c[0] for c in calls])
  self.assertIn("content_materialize",[c[0] for c in calls])

if __name__=="__main__":unittest.main()
