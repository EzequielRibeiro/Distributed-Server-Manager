import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"dashboard"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"database"))
from minecraft_current_neoforge_event_persistence import persist_current_neoforge_attestations
CLAIM={"kind":"MinecraftNeoForgeCurrentAttestation","agent_id":"a","instance_id":"i",
       "loader_version":"26.1.2.94","observed_at":"2026-10-24T10:00:00Z"}
class CurrentPersistenceTests(unittest.TestCase):
 def test_new_event_never_impersonates_historical_recovery(self):
  with patch("minecraft_current_neoforge_event_persistence.UniversalEventRepository") as repo:
   repo.return_value.publish.return_value={"created":True}
   result=persist_current_neoforge_attestations(object(),[CLAIM,CLAIM])
   self.assertEqual(result,{"accepted":1,"created":1})
   event=repo.return_value.publish.call_args.args[0]
   self.assertEqual(event["event_type"],"MINECRAFT_NEOFORGE_CURRENT_VERIFIED")
   self.assertEqual(event["data"]["proof_scope"],"current_runtime_only")
   self.assertNotIn("recovered_at",event["data"])
 def test_invalid_kind_rejected(self):
  with patch("minecraft_current_neoforge_event_persistence.UniversalEventRepository") as repo:
   self.assertEqual(persist_current_neoforge_attestations(object(),[{**CLAIM,"kind":"recovered"}])["accepted"],0)
   repo.return_value.publish.assert_not_called()
if __name__=="__main__":unittest.main()
