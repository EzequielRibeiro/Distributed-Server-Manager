"""Issue #984: DayZ BattlEye path UI + safe persisted Controller declaration.

This milestone does not dispatch a runtime rewrite. A later controlled
materialization must reconcile the Agent's RuntimeSpec before use.
"""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
for module in (ROOT/'database', ROOT/'dashboard', ROOT/'core'):
    sys.path.insert(0,str(module))

from instance_workspace_policy import validate_startup_values
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from runtime_workspace_catalog import runtime_workspace_capabilities

class DayZBEPathCustomerWorkspaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.declaration=runtime_workspace_capabilities(ROOT,'dayz','dayz.stable')['startup_parameters']
    def test_declaration_default_and_safe_format(self):
        entry=self.declaration['battleye_directory']
        self.assertTrue(entry['customer_editable'])
        self.assertEqual(entry['default'],'battleye')
        self.assertTrue(entry['restart_required'])
        self.assertEqual(entry['format'],'instance_private_subdirectory')

    def test_accepts_only_private_relative_subdirectories(self):
        for value in ('battleye','anticheat/battleye','safe/one/two','abc_1/XYZ-2'):
            with self.subTest(value=value):
                self.assertEqual(validate_startup_values({'battleye_directory':value},self.declaration),{'battleye_directory':value})
        for value in ('','/etc','../escape','a/../x','a//b','a/b/c/d','-bad','a\\b','a b','a;run','A'*65,'a/./b','a\x00b',123):
            with self.subTest(rejected=value):
                with self.assertRaises(ValueError):
                    validate_startup_values({'battleye_directory':value},self.declaration)
        with self.assertRaises(PermissionError):
            validate_startup_values({'-BEpath':'/tmp'},self.declaration)

    def test_controller_service_reads_default_and_saves_without_agent_action(self):
        s=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService)
        s.root=ROOT
        s.repo=Mock()
        s.repo.workspace_policy.return_value={'startup':{}}
        s.repo.save_workspace_policy.side_effect=lambda instance,policy: dict(policy)
        context={'game_id':'dayz','runtime_id':'dayz.stable'}
        with patch.object(s,'require',return_value=context) as require:
            read=s.startup({'role':'customer'},'client-dayz')
            self.assertEqual(read['values']['battleye_directory'],'battleye')
            result=s.save_startup({'role':'customer'},'client-dayz',{'battleye_directory':'private/battleye'})
        self.assertEqual(result['startup']['battleye_directory'],'private/battleye')
        self.assertEqual(s.repo.save_workspace_policy.call_count,1)
        self.assertEqual(require.call_args.args[-1],'startup.write')
        with patch.object(s,'require',return_value=context):
            with self.assertRaises(ValueError):
                s.save_startup({},'client-dayz',{'battleye_directory':'/etc'})
        self.assertEqual(s.repo.save_workspace_policy.call_count,1)

    def test_ui_never_dispatches_restart_or_raw_bepath_flag(self):
        ui=(ROOT/'dashboard/web/customer-instance-v2.js').read_text()
        self.assertIn('spec.label||key',ui)
        self.assertIn('n.dataset.key==="battleye_directory"',ui)
        self.assertIn('Aplicação pelo Agent exige rematerialização controlada',ui)
        self.assertNotIn('values["-BEpath"]',ui)

    def test_agent_profile_context_persists_structured_preference(self):
        runtime=(ROOT/'agents/linux/runtime/game_runtime.py').read_text()
        self.assertIn('"battleye_directory",',runtime)
        profile=(ROOT/'agents/linux/runtime/profiles/dayz.py').read_text()
        self.assertIn('battleye_relative = context.get("battleye_directory", "battleye")',profile)
        self.assertIn('f"-BEpath={battleye_path}"',profile)

if __name__=='__main__':
    unittest.main()
