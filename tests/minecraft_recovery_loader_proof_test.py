#!/usr/bin/env python3
import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT/"agents"/"linux"/"runtime",ROOT/"agents"/"common"):
 sys.path.insert(0,str(p))
from minecraft_recovery_loader_proof import verify_recovered_loader
REC={"instance_id":"mc","agent_id":"a","operation":"minecraft_serverpack_migration","status":"recovered","recovery":{"manual_recovery_required":False,"original_loader_version":"26.1.2.94"}}
class ProofTests(unittest.TestCase):
 def test_requires_live_authoritative_verifier(self):
  with tempfile.TemporaryDirectory() as d:
   record={"instance_id":"mc","agent_id":"a","working_directory":d}
   with patch("minecraft_recovery_loader_proof.verify_installed_neoforge",return_value={"evidence":"instance-local-launcher"}) as verifier:
    self.assertTrue(verify_recovered_loader(record,REC,instance_id="mc",agent_id="a")["verified"])
    verifier.assert_called_once()
   with patch("minecraft_recovery_loader_proof.verify_installed_neoforge",side_effect=ValueError("mismatch")):
    self.assertIsNone(verify_recovered_loader(record,REC,instance_id="mc",agent_id="a"))
 def test_cross_agent_denied(self):
  self.assertIsNone(verify_recovered_loader({"instance_id":"mc","agent_id":"other"},REC,instance_id="mc",agent_id="a"))
if __name__=="__main__":unittest.main()
