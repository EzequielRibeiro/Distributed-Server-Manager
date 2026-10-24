#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"dashboard"))
from minecraft_recovery_customer_projection import visible_provision_after_recovery
FAILED={"status":"failed","progress":99,"last_error":"historical failure"}
VERIFIED={"status":"recovered_verified","allow_clear_previous_failure":True,
          "healthy":True,"loader_verified":True,"failure_matches_recovery":True}
class ProjectionTests(unittest.TestCase):
 def test_verified_recovery_hides_only_customer_warning(self):
  original=dict(FAILED)
  self.assertIsNone(visible_provision_after_recovery(original,VERIFIED))
  self.assertEqual(original,FAILED)
 def test_unverified_or_incomplete_evidence_is_visible(self):
  for key in VERIFIED:
   data=dict(VERIFIED)
   data[key]=False if isinstance(data[key],bool) else "unverified"
   with self.subTest(key=key):
    self.assertEqual(visible_provision_after_recovery(FAILED,data),FAILED)
  self.assertEqual(visible_provision_after_recovery(FAILED,None),FAILED)
 def test_new_running_or_failed_operations_not_hidden(self):
  self.assertEqual(visible_provision_after_recovery({"status":"running","progress":99},VERIFIED),{"status":"running","progress":99})
  self.assertEqual(visible_provision_after_recovery({"status":"completed","progress":100},VERIFIED),{"status":"completed","progress":100})
if __name__=="__main__":unittest.main()
