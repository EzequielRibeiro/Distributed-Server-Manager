#!/usr/bin/env python3
"""Safety regression: recorded claims must not automatically clear a failed install."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"dashboard"))
from minecraft_recovery_observation_contract import validate_recovery_observation
from recovered_provisioning_evidence import recovered_previous_failure

RAW=dict(kind="MinecraftServerPackRecoveryObservation",schema_version=1,
 instance_id="mc005",agent_id="agent1",operation="minecraft_serverpack_migration",
 status="recovered",filesystem_status="recovered",original_loader_version="26.1.2.94",
 recovered_at="2026-10-23T23:28:00Z",observed_at="2026-10-23T23:29:00Z")
FAILED=dict(instance_id="mc005",agent_id="agent1",status="failed",
 completed_at="2026-10-22T23:00:00Z")
class RecoveryChainSafetyTest(unittest.TestCase):
 def test_sanitized_observation_is_not_health_proof(self):
  claim=validate_recovery_observation(RAW,authenticated_agent_id="agent1",expected_instance_id="mc005")
  self.assertIsNotNone(claim)
  self.assertFalse(recovered_previous_failure(FAILED,claim,expected_instance_id="mc005",
   expected_agent_id="agent1",live_state="running",reconcile_status="healthy"))
 def test_old_claim_cannot_hide_new_failed_attempt(self):
  claim={**RAW,"authenticated_agent_observation":True,"original_loader_verified":True}
  newer={**FAILED,"completed_at":"2026-10-24T00:00:00Z"}
  self.assertFalse(recovered_previous_failure(newer,claim,expected_instance_id="mc005",
   expected_agent_id="agent1",live_state="running",reconcile_status="healthy"))
if __name__=="__main__":unittest.main()
