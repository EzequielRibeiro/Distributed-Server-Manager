import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"dashboard"))
from minecraft_current_neoforge_heartbeat_claims import current_attestations_from_heartbeat as accept
OK={"kind":"MinecraftNeoForgeCurrentAttestation","agent_id":"agent","instance_id":"mc005",
    "loader_version":"26.1.2.94","verified":True,"observed_at":"2026-10-24T10:00:00Z"}
def validate(entries, agent="agent", owned=None):
    return accept({"minecraft_current_neoforge_attestations":entries},
                  authenticated_agent_id=agent,owned_instance_ids={"mc005"} if owned is None else owned)
class CurrentClaimsTests(unittest.TestCase):
    def test_accepted_claim_does_not_reconstruct_migration(self):
        entries=validate([OK])
        self.assertEqual(len(entries),1)
        self.assertNotIn("recovered_at",entries[0])
        self.assertNotIn("allow_clear_previous_failure",entries[0])
    def test_wrong_agent_and_ownership_rejected(self):
        self.assertEqual(validate([OK],agent="other"),[])
        self.assertEqual(validate([OK],owned=set()),[])
    def test_invalid_timestamp_and_version_rejected(self):
        self.assertEqual(validate([{**OK,"observed_at":"2026-10-24"}]),[])
        self.assertEqual(validate([{**OK,"loader_version":"../../bad"}]),[])
    def test_unverified_claim_rejected(self):
        self.assertEqual(validate([{**OK,"verified":False}]),[])
    def test_bounded_and_deduplicated(self):
        self.assertEqual(validate([OK,OK]).__len__(),1)
        self.assertEqual(validate([OK]*129),[])
if __name__=="__main__":unittest.main()
