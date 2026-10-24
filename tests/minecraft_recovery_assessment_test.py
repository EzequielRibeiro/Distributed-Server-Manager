#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"database"):
 sys.path.insert(0,str(path))
from minecraft_recovery_assessment import recovery_assessment
EV={"source":"controller.authenticated_agent_recovery","agent_id":"a","instance_id":"i","occurred_at":"2026-10-23T23:28:00Z"}
FAILED={"instance_id":"i","agent_id":"a","status":"failed","completed_at":"2026-10-23T23:20:00Z"}
class AssessmentTests(unittest.TestCase):
 def test_recorded_and_healthy_still_cannot_clear_failure(self):
  with patch("minecraft_recovery_assessment.UniversalEventRepository") as events,patch("minecraft_recovery_assessment.AgentInstanceRuntimeHealthRepository") as health,patch("minecraft_recovery_assessment.AgentInstanceProvisioningRepository") as provision:
   provision.return_value.latest_for_instance.return_value=FAILED
   provision.return_value.latest_for_instance.return_value=FAILED
   events.return_value.list_events.return_value=[EV]
   health.return_value.list_for_agent.return_value=[{"instance_id":"i","observed_state":"running","reconcile_status":"healthy","health":"healthy","reported_at":"2026-10-23T23:30:00Z"}]
   result=recovery_assessment(object(),instance_id="i",agent_id="a")
  self.assertTrue(result["audit_recorded"])
  self.assertTrue(result["healthy"])
  self.assertFalse(result["loader_verified"])
  self.assertFalse(result["allow_clear_previous_failure"])
 def test_stale_health_cannot_validate_recovery(self):
  with patch("minecraft_recovery_assessment.UniversalEventRepository") as events,patch("minecraft_recovery_assessment.AgentInstanceRuntimeHealthRepository") as health,patch("minecraft_recovery_assessment.AgentInstanceProvisioningRepository") as provision:
   provision.return_value.latest_for_instance.return_value=FAILED
   events.return_value.list_events.return_value=[EV]
   health.return_value.list_for_agent.return_value=[{"instance_id":"i","observed_state":"running","reconcile_status":"healthy","health":"healthy","reported_at":"2026-10-23T23:27:00Z"}]
   result=recovery_assessment(object(),instance_id="i",agent_id="a")
  self.assertTrue(result["audit_recorded"])
  self.assertFalse(result["healthy"])
  self.assertFalse(result["allow_clear_previous_failure"])
 def test_newer_failure_cannot_match_old_recovery(self):
  with patch("minecraft_recovery_assessment.UniversalEventRepository") as events,patch("minecraft_recovery_assessment.AgentInstanceProvisioningRepository") as provision:
   provision.return_value.latest_for_instance.return_value=FAILED
   events.return_value.list_events.return_value=[EV]
   provision.return_value.latest_for_instance.return_value={**FAILED,"completed_at":"2026-10-24T00:00:00Z"}
   result=recovery_assessment(object(),instance_id="i",agent_id="a")
  self.assertTrue(result["audit_recorded"])
  self.assertFalse(result["failure_matches_recovery"])
  self.assertFalse(result["allow_clear_previous_failure"])
 def test_other_agent_event_rejected(self):
  with patch("minecraft_recovery_assessment.UniversalEventRepository") as events:
   events.return_value.list_events.return_value=[{**EV,"agent_id":"other"}]
   self.assertFalse(recovery_assessment(object(),instance_id="i",agent_id="a")["audit_recorded"])
if __name__=="__main__":unittest.main()
