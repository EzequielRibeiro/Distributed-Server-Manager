#!/usr/bin/env python3
"""Hybrid current proof collection cannot revise provisioning or claim recovery."""
import sys, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"dashboard/workers",ROOT/"database"):
 sys.path.insert(0,str(path))
from hybrid_agent_worker import process_hybrid_current_neoforge_attestation_cycle
class HybridCurrentAttestationTests(unittest.TestCase):
 def test_missing_environment_fails_closed_without_mutations(self):
  with patch("hybrid_agent_worker._instance_runtime_module",side_effect=RuntimeError("offline")):
   result=process_hybrid_current_neoforge_attestation_cycle(object(),Path("/nonexistent/dsm"),"agent")
  self.assertEqual(result,{"status":"unavailable","verified":0})
if __name__=="__main__":unittest.main()
