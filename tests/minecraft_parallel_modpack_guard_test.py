"""Persistence-level installation lock for independent Minecraft content changes."""
from __future__ import annotations
import threading
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
   self.repo.put(self.owner.assignment('1'),customer_install_guard=True)
  self.assertIsNone(self.repo.get('inst','mod-one'))
  self.report('pack','applied')
  with self.assertRaisesRegex(ContentValidationError,'dependências'):
   self.repo.put(self.owner.assignment('1'),customer_install_guard=True)
  self.report('child-a','applied')
  self.assertTrue(self.repo.put(self.owner.assignment('1'),customer_install_guard=True)['changed'])
 def test_parent_terminal_failure_releases_other_install(self):
  self.report('pack','failed')
  self.assertTrue(self.repo.put(self.owner.assignment('1'),customer_install_guard=True)['changed'])
 def test_same_parent_duplicate_blocked_until_all_children_settle(self):
  update=lambda:self.repo.put_bundle(self.owner.parent('2'),
     fixture._bundle('v2',[fixture._member('child-a')]),
     [self.owner.child('child-a')],customer_install_guard=True)
  with self.assertRaisesRegex(ContentValidationError,'modpack'):update()
  self.report('pack','applied')
  with self.assertRaisesRegex(ContentValidationError,'dependências'):update()
  self.report('child-a','applied')
  result=update()
  self.assertTrue(result['changed'])
  self.assertEqual(self.repo.get('inst','pack')['version'],'2')
  with self.assertRaisesRegex(ContentValidationError,'modpack'):
   self.repo.put_bundle(self.owner.parent('3'),
      fixture._bundle('v3',[fixture._member('child-a')]),
      [self.owner.child('child-a')],customer_install_guard=True)

 def test_two_concurrent_customer_sessions_allow_only_one_update(self):
  # Two independent Controller requests share SQLite but not an HTTP session.
  # BEGIN IMMEDIATE serializes their writes; the losing request must detect
  # the first request's unacknowledged modpack revision.
  from content_repository import ContentRepository
  self.report('pack','applied')
  self.report('child-a','applied')
  repo2=ContentRepository(self.owner.backend)
  start=threading.Barrier(3)
  results=[]
  def attempt(repo,version):
   try:
    start.wait(timeout=5)
    value=repo.put_bundle(self.owner.parent(version),
     fixture._bundle('v'+version,[fixture._member('child-a')]),
     [self.owner.child('child-a')],customer_install_guard=True)
    results.append(('success',value['assignment']['revision']))
   except ContentValidationError:results.append(('blocked',version))
   except Exception as exc:results.append(('unexpected',repr(exc)))
  threads=[threading.Thread(target=attempt,args=(repo,version))
           for repo,version in ((self.repo,'2'),(repo2,'3'))]
  for thread in threads:thread.start()
  start.wait(timeout=5)
  for thread in threads:thread.join(timeout=15)
  self.assertTrue(all(not thread.is_alive() for thread in threads))
  self.assertEqual(sorted(label for label,_ in results),['blocked','success'],results)
  self.assertEqual(self.repo.get('inst','pack')['revision'],2)


if __name__=='__main__':unittest.main()
