"""#984: a saved customer preference needs explicit, stopped-only Agent application."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agents/linux/runtime'))
sys.path.insert(0,str(ROOT/'database'))
from profiles.dayz import DayZRuntimeProfile
import dayz_operation_client as operation
from dayz_management_repository import VALID_ACTIONS,MUTATING_ACTIONS

class DayZBEPathControlledApplyTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dsm984-')
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.private=root/'instance-private'
        self.private.mkdir()
        profile=DayZRuntimeProfile()
        instance={'instance_id':'dayz-984','agent_id':'agent-984'}
        context={'install_path':str(root/'steam-game'),
                 'instance_state_root':str(self.private),
                 'ports':{'game':24000,'game_aux':24002,'battleye':24004,'steam_query':24003}}
        self.record=profile.build_runtime_spec(instance,context)
        self.record['desired_state']='stopped'
        self.record['profile_context']=dict(context)
        self.config={'agent_id':'agent-984'}
        self.iid='dayz-984'

    def test_repository_dispatch_is_explicit_mutation(self):
        self.assertIn('apply_battleye_directory',VALID_ACTIONS)
        self.assertIn('apply_battleye_directory',MUTATING_ACTIONS)

    def test_reconciles_only_battleye_owned_flags_and_path(self):
        before=self.record
        old=str(self.private/'battleye')
        after=operation._prepare_battleye_spec(before,'anti/cheat')
        new=str(self.private/'anti/cheat')
        self.assertIn('-BEpath='+new,after['arguments'])
        self.assertNotIn('-BEpath='+old,after['arguments'])
        self.assertEqual(after['writable_directories'],[new if p==old else p for p in before['writable_directories']])
        self.assertEqual(after['working_directory'],before['working_directory'])
        self.assertEqual(after['bind_paths'],before['bind_paths'])
        self.assertEqual(after['profile_context']['battleye_directory'],'anti/cheat')
        self.assertNotIn('battleye_directory',before['profile_context'])
        self.assertEqual(after['user'],before['user'])

    def test_existing_mod_arguments_and_base_arguments_are_preserved(self):
        self.record['content_base_arguments']=list(self.record['arguments'])
        self.record['arguments']=[*self.record['arguments'],'-mod=@CF','-servermod=@VPP']
        after=operation._prepare_battleye_spec(self.record,'other')
        self.assertEqual(after['arguments'][-2:],['-mod=@CF','-servermod=@VPP'])
        self.assertIn('-BEpath='+str(self.private/'other'),after['content_base_arguments'])

    def test_invalid_paths_or_unmanaged_bepath_are_rejected(self):
        for path in ('/etc','../escape','a/../../b','x y','x//y','x/y/z/q',None):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    operation._prepare_battleye_spec(self.record,path)
        for bad in ('-BEpath /etc','-bepath=/tmp/foo','-bepath'):
            modified=dict(self.record,arguments=[*self.record['arguments'],bad])
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                operation._prepare_battleye_spec(modified,'clean')
        with self.assertRaises(ValueError):
            operation._apply_battleye_directory(self.config,self.record,self.iid,
                                                {'battleye_directory':'safe','other':'bad'})

    def test_symlink_target_is_rejected(self):
        (self.private/'link').symlink_to(self.private.parent)
        with self.assertRaises(ValueError):
            operation._prepare_battleye_spec(self.record,'link/sub')

    def test_running_server_is_never_restarted_or_materialized(self):
        with mock.patch.object(operation,'status',return_value={'observed_state':'running'}),\
             mock.patch.object(operation.privileged_materialization,'materialize') as materialize,\
             mock.patch.object(operation,'lifecycle') as lifecycle:
            with self.assertRaises(RuntimeError):
                operation._apply_battleye_directory(self.config,self.record,self.iid,
                                                     {'battleye_directory':'safe'})
            lifecycle.assert_not_called()
            materialize.assert_not_called()

    def test_stopped_server_is_materialized_once_without_restart(self):
        with mock.patch.object(operation,'status',return_value={'observed_state':'stopped'}),\
             mock.patch.object(operation.privileged_materialization,'materialize') as materialize,\
             mock.patch.object(operation,'lifecycle') as lifecycle:
            result=operation._apply_battleye_directory(self.config,self.record,self.iid,
                                                        {'battleye_directory':'private/be'})
            self.assertEqual(result['battleye_directory'],'private/be')
            self.assertTrue(result['applied'])
            self.assertFalse(result['restarted'])
            self.assertEqual(materialize.call_count,1)
            self.assertEqual(materialize.call_args.args[1]['instance_id'],self.iid)
            lifecycle.assert_not_called()

    def test_failed_materialization_rolls_back_original_spec(self):
        with mock.patch.object(operation,'status',return_value={'observed_state':'stopped'}),\
             mock.patch.object(operation.privileged_materialization,'materialize',
                               side_effect=[RuntimeError('simulate failure'),{'ok':True}]) as materialize:
            with self.assertRaisesRegex(RuntimeError,'previous runtime restored'):
                operation._apply_battleye_directory(self.config,self.record,self.iid,
                                                     {'battleye_directory':'clean'})
            self.assertEqual(materialize.call_count,2)
            self.assertEqual(materialize.call_args_list[-1].args[1],self.record)

    def test_idempotent_apply_skips_privileged_write(self):
        with mock.patch.object(operation,'status',return_value={'observed_state':'stopped'}),\
             mock.patch.object(operation.privileged_materialization,'materialize') as materialize:
            result=operation._apply_battleye_directory(self.config,self.record,self.iid,
                                                        {'battleye_directory':'battleye'})
            self.assertFalse(result['changed'])
            materialize.assert_not_called()

if __name__=='__main__':
    unittest.main()
