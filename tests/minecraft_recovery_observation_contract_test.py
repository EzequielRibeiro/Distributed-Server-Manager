#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"dashboard"))
from minecraft_recovery_observation_contract import validate_recovery_observation
CLAIM=dict(kind="MinecraftServerPackRecoveryObservation",schema_version=1,
  instance_id="minecraft-005",agent_id="agent-horizon",
  operation="minecraft_serverpack_migration",status="recovered",
  filesystem_status="recovered",original_loader_version="26.1.2.94",
  recovered_at="2026-10-23T23:28:00Z",observed_at="2026-10-23T23:29:00Z")
def check(payload=None,**kwargs):
    options=dict(authenticated_agent_id="agent-horizon",expected_instance_id="minecraft-005")
    options.update(kwargs)
    return validate_recovery_observation(CLAIM if payload is None else payload,**options)
class ContractTest(unittest.TestCase):
    def test_valid_observation_is_bounded(self):
        result=check()
        self.assertEqual(result["original_loader_version"],"26.1.2.94")
        self.assertNotIn("authenticated_agent_observation",result)
        self.assertNotIn("original_loader_verified",result)
    def test_loader_proof_is_scoped_agent_claim_not_controller_attestation(self):
        proof = {"verified":True, "instance_id":"minecraft-005",
                 "agent_id":"agent-horizon","loader_version":"26.1.2.94",
                 "evidence":"instance-local-launcher"}
        result=check({**CLAIM,"loader_proof":proof})
        self.assertTrue(result["agent_reported_loader_proof"])
        self.assertNotIn("original_loader_verified",result)
        self.assertFalse(check({**CLAIM,"loader_proof":{**proof,"agent_id":"other"}})["agent_reported_loader_proof"])

    def test_cross_agent_and_instance(self):
        self.assertIsNone(check(authenticated_agent_id="other"))
        self.assertIsNone(check(expected_instance_id="other"))
    def test_invalid_state_and_time(self):
        self.assertIsNone(check({**CLAIM,"status":"failed"}))
        self.assertIsNone(check({**CLAIM,"observed_at":"2026-10-23T23:00:00Z"}))
        self.assertIsNone(check({**CLAIM,"recovered_at":"na"}))
    def test_untrusted_claims_stripped(self):
        result=check({**CLAIM,"authenticated_agent_observation":True,"original_loader_verified":True,"secrets":"no"})
        self.assertNotIn("secrets",result)
        self.assertNotIn("authenticated_agent_observation",result)
if __name__=="__main__":unittest.main()
