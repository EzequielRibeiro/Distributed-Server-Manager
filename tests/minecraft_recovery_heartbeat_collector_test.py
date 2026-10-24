#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"agents"/"linux"/"runtime"))
from minecraft_recovery_heartbeat_collector import collect_recovery_observations
RECORD={"instance_id":"mc005","agent_id":"agent1","operation":"minecraft_serverpack_migration","status":"recovered",
"recovered_at":"2026-10-23T23:28:00Z",
"recovery":{"kind":"MinecraftServerPackMigrationRecovery","filesystem_status":"recovered",
"manual_recovery_required":False,"original_loader_version":"26.1.2.94"}}
class CollectorTest(unittest.TestCase):
 def test_matching_journal(self):
  got=collect_recovery_observations(["mc005","mc005"],agent_id="agent1",read_operation=lambda _:RECORD,observed_at="2026-10-23T23:29:00Z")
  self.assertEqual(len(got),1)
  self.assertEqual(got[0]["status"],"recovered")
 def test_wrong_agent_and_failed_are_omitted(self):
  self.assertEqual(collect_recovery_observations(["mc005"],agent_id="other",read_operation=lambda _:RECORD),[])
  self.assertEqual(collect_recovery_observations(["mc005"],agent_id="agent1",read_operation=lambda _:{**RECORD,"status":"failed"}),[])
 def test_broken_journal_and_time_are_omitted(self):
  self.assertEqual(collect_recovery_observations(["mc005"],agent_id="agent1",read_operation=lambda _:None),[])
  self.assertEqual(collect_recovery_observations(["mc005"],agent_id="agent1",read_operation=lambda _:RECORD,observed_at="invalid"),[])
if __name__=="__main__":unittest.main()
