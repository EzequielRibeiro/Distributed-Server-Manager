#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"core"))
from federation import FederationMember,FederationValidationError,build_inventory_snapshot

class FederationContractTest(unittest.TestCase):
 def test_datacenter_member_requires_location(self):
  with self.assertRaises(FederationValidationError):FederationMember("ctrl-a","datacenter").normalized()
 def test_https_endpoint_is_required(self):
  with self.assertRaises(FederationValidationError):FederationMember("ctrl-a","regional",region_id="br-se",public_endpoint="http://example.test").normalized()
 def test_inventory_snapshot_is_deterministic(self):
  kw=dict(controller_id="ctrl-a",generated_at="2026-08-21T19:00:00Z",agents=[{"id":"a1"}],instances=[{"id":"i1"}],capacity={"cpu":4})
  self.assertEqual(build_inventory_snapshot(**kw)["snapshot_id"],build_inventory_snapshot(**kw)["snapshot_id"])
 def test_snapshot_is_controller_scoped(self):
  a=build_inventory_snapshot(controller_id="ctrl-a",generated_at="2026-08-21T19:00:00Z")
  b=build_inventory_snapshot(controller_id="ctrl-b",generated_at="2026-08-21T19:00:00Z")
  self.assertNotEqual(a["snapshot_id"],b["snapshot_id"])
if __name__=="__main__":unittest.main()
