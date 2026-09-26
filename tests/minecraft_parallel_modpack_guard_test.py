"""Persistence-level installation lock for independent Minecraft content changes."""
from __future__ import annotations
import unittest
from tests import universal_content_update_rollback_test as fixture
from content_platform import ContentValidationError

class ParallelModpackGuardTest(unittest.TestCase):
 def setUp(self):
  self.owner=fixture.UniversalContentUpdateRollbackTest()
  self.owner.setUp()
  self.repo=self.owner.repo
  self.repo.put_bundle(self.owner.parent('1'),fixture._bundle('v1',[fixture._member('child-a')]),[self.owner.child('child-a')])
 def tearDown(self):self.owner.tearDown()
 def report(self,content_id,status):
  value=self.repo.get('inst',content_id)
  self.repo.record_agent_state('agent',[dict(instance_id='inst',content_id=content_id,
    desired_revision=value['revision'],applied_revision=value['revision'] if status=='applied' else None,
    desired_checksum=value['checksum'],applied_checksum=value['checksum'] if status=='applied' else None,
    status=status,installed_version=value.get('version'),security_state='clean')])
 def test_blocks_other_install_until_parent_and_child_are_applied(self):
  with self.assertRaisesRegex(ContentValidationError,'modpack'):
   self.repo.put(self.owner.assignment('1'))
  self.assertIsNone(self.repo.get('inst','mod-one'))
  self.report('pack','applied')
  with self.assertRaisesRegex(ContentValidationError,'dependências'):
   self.repo.put(self.owner.assignment('1'))
  self.report('child-a','applied')
  self.assertTrue(self.repo.put(self.owner.assignment('1'))['changed'])
 def test_parent_terminal_failure_releases_other_install(self):
  self.report('pack','failed')
  self.assertTrue(self.repo.put(self.owner.assignment('1'))['changed'])
 def test_same_parent_revision_semantics_preserved(self):
  result=self.repo.put_bundle(self.owner.parent('2'),fixture._bundle('v2',[fixture._member('child-a')]),
                              [self.owner.child('child-a')])
  self.assertTrue(result['changed'])
  self.assertEqual(self.repo.get('inst','pack')['version'],'2')

if __name__=='__main__':unittest.main()
