import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"agents/linux/runtime"))
from minecraft_current_neoforge_collector import collect_current_neoforge_attestations as collect
class CollectorTest(unittest.TestCase):
 def test_current_loader_proof_no_historical_claim(self):
  with tempfile.TemporaryDirectory() as tmp:
   record={"instance_id":"mc005","agent_id":"hybrid","runtime_id":"minecraft.java.neoforge",
           "working_directory":tmp,"content_root":"/srv/game-data/minecraft/neoforge/26.1.2/26.1.2.94"}
   with patch("minecraft_current_neoforge_attestation.verify_installed_neoforge",return_value={"evidence":{"launch":"ok"}}):
    proof=collect(["mc005"],agent_id="hybrid",read_instance=lambda _:record)
   self.assertEqual(len(proof),1)
   self.assertEqual(proof[0]["loader_version"],"26.1.2.94")
   self.assertNotIn("recovered_at",proof[0])
 def test_wrong_runtime_and_bad_source_rejected(self):
  record={"instance_id":"mc005","agent_id":"hybrid","runtime_id":"minecraft.java.vanilla",
          "content_root":"/srv/neoforge/26.1.2/26.1.2.94"}
  self.assertEqual(collect(["mc005"],agent_id="hybrid",read_instance=lambda _:record),[])
  record["runtime_id"]="minecraft.java.neoforge"
  record["content_root"]="/tmp/fake/26.1.2.94"
  self.assertEqual(collect(["mc005"],agent_id="hybrid",read_instance=lambda _:record),[])
if __name__=="__main__":unittest.main()
