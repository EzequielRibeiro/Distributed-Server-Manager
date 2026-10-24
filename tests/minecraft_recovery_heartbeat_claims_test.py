#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"dashboard"))
from minecraft_recovery_heartbeat_claims import recovery_claims_from_heartbeat, validated_heartbeat_recovery_claims
from unittest.mock import patch

CLAIM = {
    "kind":"MinecraftServerPackRecoveryObservation","schema_version":1,
    "instance_id":"mc005","agent_id":"agent1",
    "operation":"minecraft_serverpack_migration","status":"recovered",
    "filesystem_status":"recovered","original_loader_version":"26.1.2.94",
    "recovered_at":"2026-10-23T23:28:00Z","observed_at":"2026-10-23T23:29:00Z",
}
def project(items, *, owner="agent1", ids=None):
    return recovery_claims_from_heartbeat(
        {"minecraft_recovery_observations":items},
        authenticated_agent_id=owner,
        owned_instance_ids={"mc005"} if ids is None else ids,
    )
class HeartbeatClaimsTests(unittest.TestCase):
    def test_owned_authenticated_claim(self):
        self.assertEqual(len(project([CLAIM])),1)
    def test_reject_wrong_agent_and_unowned_instance(self):
        self.assertEqual(project([CLAIM],owner="agent2"),[])
        self.assertEqual(project([CLAIM],ids=set()),[])
    def test_reject_invalid_and_duplicate(self):
        self.assertEqual(len(project([CLAIM,CLAIM,{"status":"failed"},None])),1)
    def test_owned_ids_resolved_on_server(self):
        with patch("minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent", return_value={"mc005"}) as owned:
            result=validated_heartbeat_recovery_claims(object(), {"minecraft_recovery_observations":[CLAIM]},authenticated_agent_id="agent1")
        owned.assert_called_once()
        self.assertEqual(len(result),1)
    def test_server_ownership_denial(self):
        with patch("minecraft_recovery_heartbeat_claims.owned_instance_ids_for_agent", return_value=set()):
            result=validated_heartbeat_recovery_claims(object(), {"minecraft_recovery_observations":[CLAIM]},authenticated_agent_id="agent1")
        self.assertEqual(result,[])

    def test_bounded_input(self):
        self.assertEqual(project([CLAIM]*129),[])
    def test_no_privilege_from_claim(self):
        result=project([{**CLAIM,"original_loader_verified":True,"authenticated_agent_observation":True}])[0]
        self.assertNotIn("original_loader_verified",result)
        self.assertNotIn("authenticated_agent_observation",result)
if __name__=="__main__":unittest.main()
