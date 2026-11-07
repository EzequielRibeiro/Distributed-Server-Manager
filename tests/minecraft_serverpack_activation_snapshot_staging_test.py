from __future__ import annotations
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for root in (ROOT,ROOT/"agents/linux/runtime"):
 if str(root) not in sys.path:sys.path.insert(0,str(root))
from content_activation_projection import build_activation_snapshot_from_states


def sample(cid="mod-a",desired="installed",**update):
 state={
  "instance_id":"test-instance","content_id":cid,"content_type":"mod",
  "status":"applied","desired_state":desired,
  "desired_revision":2,"applied_revision":2,
  "desired_checksum":"abc","applied_checksum":"abc",
  "installed_version":"1.0" if desired=="installed" else None,
  "managed_path":"/nonlive/mods/"+cid if desired=="installed" else None,
  "security_state":"clean" if desired=="installed" else "unscanned",
  "applied_security_state":"clean" if desired=="installed" else "unscanned",
  "security_policy_version":1,"activation_state":"enabled",
 }
 state.update(update)
 return state


class SnapshotStageTests(unittest.TestCase):
 def build(self,states):return build_activation_snapshot_from_states("test-instance",states)
 def test_snapshot_deterministic_and_order_independent(self):
  a,b=sample(),sample("mod-b")
  first=self.build([b,a]);second=self.build([a,b])
  self.assertEqual(first,second)
  self.assertEqual(len(first["entries"]),2)
 def test_removed_legacy_state_not_in_snapshot(self):
  value=self.build([sample(),sample("old","absent")])
  self.assertEqual(len(value["entries"]),1)
 def test_reject_duplicate(self):
  with self.assertRaisesRegex(ValueError,"duplicate"):
   self.build([sample(),sample()])
 def test_reject_foreign(self):
  with self.assertRaisesRegex(ValueError,"foreign"):
   self.build([sample(instance_id="other")])
 def test_reject_stale_revision(self):
  with self.assertRaisesRegex(ValueError,"incomplete"):
   self.build([sample(applied_revision=1)])
 def test_reject_blocked_security(self):
  with self.assertRaisesRegex(ValueError,"unverified"):
   self.build([sample(security_state="unscanned")])
 def test_reject_removed_content_with_file(self):
  with self.assertRaisesRegex(ValueError,"removed"):
   self.build([sample(desired_state="absent")])
 def test_reject_uncommitted(self):
  with self.assertRaisesRegex(ValueError,"uncommitted"):
   self.build([sample(status="pending")])
 def test_reject_missing_installed_version(self):
  with self.assertRaisesRegex(ValueError,"incomplete"):
   self.build([sample(installed_version=None)])
 def test_reject_empty_batch(self):
  with self.assertRaisesRegex(ValueError,"nonempty"):
   self.build([])
 def test_reject_unfulfilled_dependency(self):
  with self.assertRaisesRegex(ValueError,"excluded"):
   self.build([sample(dependencies=["absent-dependency"])])
 def test_preserves_disabled_without_projecting(self):
  value=self.build([sample(activation_state="disabled")])
  self.assertEqual(value["entries"],[])


if __name__=="__main__": unittest.main()
