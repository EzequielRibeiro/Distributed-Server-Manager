"""One-shot worker policy and revalidation, all side effects mocked."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import contextmanager

R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/"agents/linux/runtime"))
import minecraft_serverpack_finalization_worker as w

class WorkerTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
  self.root=Path(self.t.name);self.cfg=self.root/"agent.json"
  self.cfg.write_text(json.dumps({"agent_id":"agent-test"}))
  self.env={"CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE":"sandbox-instance",
            "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"1",
            "CAPIVARA_AGENT_STATE_DIR":str(self.root)}
 def test_default_denied(self):
  with patch.dict(os.environ,{"CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE":"0",
                                "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER":"0"},clear=True):
   with self.assertRaises(PermissionError):w.execute_one(self.cfg,"sandbox-instance")
 def test_wrong_instance_denied(self):
  with patch.dict(os.environ,self.env,clear=True):
   with self.assertRaises(PermissionError):w.execute_one(self.cfg,"foreign")
 def test_reconcile_only_does_not_load_operational_module(self):
  seen=[]
  @contextmanager
  def lock(_):
   yield
  def scan(**kwargs):
   kwargs["dispatch"]({"instance_id":"foreign"},{"instance_id":"foreign","status":"completed"})
   kwargs["dispatch"]({"instance_id":"sandbox-instance"},{"instance_id":"sandbox-instance","status":"running"})
   return [{"instance_id":"sandbox-instance","status":"pending"}]
  with patch.dict(os.environ,self.env,clear=True), patch.object(w,"scan_pending_finalizations",scan):
   self.assertEqual(w.execute_one(self.cfg,"sandbox-instance")[0]["status"],"pending")
 def test_requires_absolute_config(self):
  with patch.dict(os.environ,self.env,clear=True):
   with self.assertRaises(ValueError):w.execute_one(Path("relative.json"),"sandbox-instance")
 def test_reconcile_without_candidate(self):
  with patch.dict(os.environ,self.env,clear=True),patch.object(w,"scan_pending_finalizations",return_value=[]):
   self.assertEqual(w.execute_one(self.cfg,"sandbox-instance"),[])

if __name__=="__main__":unittest.main()
