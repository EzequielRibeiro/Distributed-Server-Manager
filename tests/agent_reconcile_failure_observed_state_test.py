"""Failed reconciliation refreshes the observed runtime state."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"agents/linux/runtime"))
import runtime_reconciler as module

class FailureStateTest(unittest.TestCase):
    def run_failure(self, adapter_state):
        record={"instance_id":"dayz-test","agent_id":"agent-local","observed_state":"running"}
        saved=[]
        def save(row, **kwargs):
            saved.append(kwargs)
            return {**row, **kwargs}
        with patch.object(module,"_settings",return_value=(3,15,300)), patch.object(module,"_backoff",return_value=15), patch.object(module,"_save",side_effect=save), patch.object(module,"_event"), patch.object(module,"increment"), patch.object(module.instance_runtime,"_adapter_state",return_value=adapter_state):
            result=module._failure({},record,RuntimeError("script error"))
        return result,saved[0]["observed_state"]
    def test_failed_process_replaces_running(self):
        with patch.object(module.instance_runtime,"_observed_state",return_value="failed"):
            result,observed=self.run_failure({"available":True,"active_state":"failed"})
        self.assertEqual(result["status"],"retry_wait")
        self.assertEqual(observed,"failed")
    def test_missing_process_evidence_fails_closed(self):
        with patch.object(module.instance_runtime,"_observed_state",return_value="unknown"):
            result,observed=self.run_failure(None)
        self.assertEqual(result["status"],"retry_wait")
        self.assertEqual(observed,"unknown")

if __name__=="__main__":
    unittest.main()
