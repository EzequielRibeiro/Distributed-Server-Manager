import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from agent_instance_runtime_api import queue_instance_observation

class InternalEvidenceGuardTest(unittest.TestCase):
    def test_admin_cannot_queue_internal_evidence(self):
        backend=MagicMock()
        with self.assertRaises(PermissionError):
            queue_instance_observation({'agent_id':'a','instance_id':'i','action':'systemd_lifecycle_evidence'},user={'role':'admin'},backend=backend)
        backend.initialize.assert_not_called()

    def test_customer_cannot_queue_internal_evidence(self):
        with self.assertRaises(PermissionError):
            queue_instance_observation({'action':'systemd_lifecycle_evidence'},user={'role':'customer'},backend=MagicMock())

if __name__=='__main__':unittest.main()
