#!/usr/bin/env python3
"""Concurrent customer requests must reserve the update slot only once."""
from __future__ import annotations
import sys,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
for folder in ('core','database','dashboard'):
 sys.path.insert(0,str(ROOT/folder))
from server_update_repository import ServerUpdateRepository

class FakeSession:
 def __init__(self,store):self.store=store
 def execute(self,query,args):
  with self.store.lock:
   if 'AND active_job_id IS NULL' in query:
    if self.store.active or ('AND state=' in query and self.store.state!=args[-1]):return type('Cursor',(),{'rowcount':0})()
    self.store.active=args[0]
    return type('Cursor',(),{'rowcount':1})()
   if 'SET active_job_id=NULL' in query:
    if self.store.active==args[-1]:self.store.active=None
    return type('Cursor',(),{'rowcount':1})()
   raise AssertionError(query)

class FakeStore:
 def __init__(self):self.lock=threading.Lock();self.active=None;self.state='update_available'
 @contextmanager
 def session(self,transaction=False):yield FakeSession(self)

class CustomerGameUpdateConcurrencyTest(unittest.TestCase):
 def test_two_simultaneous_updates_dispatch_only_one(self):
  store=FakeStore();repo=ServerUpdateRepository.__new__(ServerUpdateRepository)
  repo.dialect=type('Dialect',(),{'placeholder':'?'})()
  repo.session=store.session
  calls=[]
  def dispatch(iid,*,requested_by,trigger_type):
   with store.lock:calls.append(iid)
   return {'run_id':'test-run'}
  repo.queue_update=dispatch
  gate=threading.Barrier(2)
  def request():
   gate.wait()
   try:return repo.queue_customer_operation('test-instance',action='update',requested_by='test-customer')
   except ValueError:return 'rejected'
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:request(),range(2)))
  self.assertEqual(len(calls),1)
  self.assertEqual(sum(result=='rejected' for result in results),1)
 def test_failed_dispatch_releases_reservation(self):
  store=FakeStore();repo=ServerUpdateRepository.__new__(ServerUpdateRepository)
  repo.dialect=type('Dialect',(),{'placeholder':'?'})();repo.session=store.session
  def fail(*args,**kwargs):raise RuntimeError('agent queue failed')
  repo.queue_update=fail
  with self.assertRaises(RuntimeError):repo.queue_customer_operation('test-instance',action='update',requested_by='test-customer')
  self.assertIsNone(store.active)
 def test_update_requires_available_state(self):
  store=FakeStore();store.state='up_to_date';repo=ServerUpdateRepository.__new__(ServerUpdateRepository)
  repo.dialect=type('Dialect',(),{'placeholder':'?'})();repo.session=store.session
  with self.assertRaises(ValueError):repo.queue_customer_operation('test-instance',action='update',requested_by='test-customer')
  self.assertIsNone(store.active)

if __name__=='__main__':unittest.main()
