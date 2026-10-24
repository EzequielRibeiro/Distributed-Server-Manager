import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents/linux/runtime"))
from minecraft_current_neoforge_attestation import attest_current_neoforge

class CurrentAttestationTests(unittest.TestCase):
    def test_current_proof_has_no_historical_recovery_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            record = {"instance_id": "i", "agent_id": "a", "working_directory": temp}
            with patch("minecraft_current_neoforge_attestation.verify_installed_neoforge",
                       return_value={"evidence": {"launch_args": "verified"}}):
                result = attest_current_neoforge(record, instance_id="i", agent_id="a", expected_version="26.1.2.94")
            self.assertEqual(result["kind"], "MinecraftNeoForgeCurrentAttestation")
            self.assertNotIn("recovered_at", result)
            self.assertNotIn("operation", result)
            self.assertNotIn("allow_clear_previous_failure", result)
    def test_agent_mismatch_rejected(self):
        with patch("minecraft_current_neoforge_attestation.verify_installed_neoforge") as verify:
            self.assertIsNone(attest_current_neoforge({"instance_id":"i","agent_id":"a","working_directory":"/tmp"},
                            instance_id="i",agent_id="b",expected_version="26.1.2.94"))
            verify.assert_not_called()
    def test_invalid_version_rejected(self):
        with patch("minecraft_current_neoforge_attestation.verify_installed_neoforge") as verify:
            self.assertIsNone(attest_current_neoforge({"instance_id":"i","agent_id":"a","working_directory":"/tmp"},
                            instance_id="i",agent_id="a",expected_version="../bad"))
            verify.assert_not_called()
    def test_missing_files_not_attested(self):
        with tempfile.TemporaryDirectory() as temp:
            record={"instance_id":"i","agent_id":"a","working_directory":temp}
            with patch("minecraft_current_neoforge_attestation.verify_installed_neoforge",return_value={}):
                self.assertIsNone(attest_current_neoforge(record,instance_id="i",agent_id="a",expected_version="26.1.2.94"))
if __name__=="__main__":
    unittest.main()
