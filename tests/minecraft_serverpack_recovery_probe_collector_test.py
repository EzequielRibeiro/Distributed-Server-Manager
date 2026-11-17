from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"agents/linux/runtime",ROOT/"agents/common",ROOT/"core"):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from minecraft_serverpack_recovery_probe_collector import latest_serverpack_recovery_probe

class CollectorTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory()
  self.addCleanup(tmp.cleanup)
  self.root=Path(tmp.name)/"provisioning";self.root.mkdir()
  (self.root/"history").mkdir()
  self.job="instance-provision-test001"
  self.pending={"kind":"pending"}
  self.result={"status":"completed","instance_id":"mc005",
               "provisioning_id":self.job,
               "minecraft_serverpack_migration":{"commit":{"journal":{"phase":"committed"}}}}
  self.probe={"provisioning_id":self.job,"instance_id":"mc005",
              "candidate_sha256":"a"*64}
 def write(self,folder=None,job=None):
  folder=folder or self.root/"history"
  job=job or self.job
  (folder/(job+".request.json")).write_text(json.dumps({
    "configuration":{"minecraft_serverpack_pending_bundle":self.pending}}))
  (folder/(job+".result.json")).write_text(json.dumps(self.result))
 def collect(self):
  with patch("minecraft_serverpack_recovery_probe_collector.build_recovery_probe",
             return_value=self.probe) as verify:
   result=latest_serverpack_recovery_probe(self.root)
  return result,verify
 def test_reads_completed_archived_request(self):
  self.write()
  value,verify=self.collect()
  self.assertEqual(value,self.probe)
  verify.assert_called_once()
 def test_reads_pending_result(self):
  self.write(self.root)
  value,_=self.collect()
  self.assertEqual(value,self.probe)
 def test_no_jobs_is_noop(self):
  self.assertIsNone(self.collect()[0])
 def test_rejects_non_serverpack_request(self):
  self.write()
  path=self.root/"history"/(self.job+".request.json")
  path.write_text('{"configuration":{}}')
  self.assertIsNone(self.collect()[0])
 def test_skips_symlinked_result(self):
  self.write()
  target=self.root/"history"/(self.job+".result.json")
  actual=self.root/"foreign.json"
  target.rename(actual)
  target.symlink_to(actual)
  self.assertIsNone(self.collect()[0])
 def test_malformed_json_skipped(self):
  self.write()
  (self.root/"history"/(self.job+".result.json")).write_text("{invalid")
  self.assertIsNone(self.collect()[0])
 def test_unverified_commit_skipped(self):
  self.write()
  with patch("minecraft_serverpack_recovery_probe_collector.build_recovery_probe",
             side_effect=ValueError("not committed")):
   self.assertIsNone(latest_serverpack_recovery_probe(self.root))
 def test_no_root_returns_none(self):
  self.assertIsNone(latest_serverpack_recovery_probe(self.root/"absent"))
 def test_limit_zero_still_safe(self):
  self.write()
  self.assertIsNone(latest_serverpack_recovery_probe(self.root,max_operations=0))


if __name__=="__main__":unittest.main()
