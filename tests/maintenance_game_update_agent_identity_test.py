#!/usr/bin/env python3
"""Maintenance completion must reject a foreign local Agent before filesystem changes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/linux/runtime'))
import maintenance_game_update as module

class MaintenanceAgentIdentityTest(unittest.TestCase):
    def test_finalize_and_rollback_reject_foreign_agent_before_side_effects(self):
        record = {'agent_id': 'foreign-agent', 'game_id': 'dayz'}
        payload = {'kind': 'CapivaraMaintenanceGameUpdateTransaction', 'instance_id': 'dayz-test', 'agent_id': 'foreign-agent', 'game_id': 'dayz', 'state': 'prepared', 'previous': '/never-touch', 'target': '/never-touch'}
        with tempfile.TemporaryDirectory() as temp:
            transaction = Path(temp) / 'transaction.json'
            transaction.write_text(json.dumps(payload))
            config = Path(temp) / 'agent.json'
            config.write_text(json.dumps({'agent_id': 'local-agent'}))
            with patch.object(module, '_path', return_value=transaction), patch.object(module, '_context', return_value=('dayz-test', record, {})), patch.dict('os.environ', {'CAPIVARA_AGENT_CONFIG': str(config)}), patch.object(module, 'commit', side_effect=AssertionError('commit invoked')), patch.object(module, 'rollback', side_effect=AssertionError('rollback invoked')), patch.object(module, '_all_stopped', side_effect=AssertionError('lifecycle invoked')):
                for operation in (module.finalize, module.rollback_transaction):
                    with self.subTest(operation=operation.__name__):
                        with self.assertRaisesRegex(Exception, 'another Agent'):
                            operation({}, 'game-update-test')
                self.assertTrue(transaction.exists())

if __name__ == '__main__':
    unittest.main()
