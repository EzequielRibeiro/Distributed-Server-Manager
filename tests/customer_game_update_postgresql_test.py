#!/usr/bin/env python3
"""Run inside pg_virtualenv against an isolated, disposable PostgreSQL cluster."""
from __future__ import annotations
import sys,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'core'),str(ROOT/'database')]
import psycopg
from server_update_repository import ServerUpdateRepository

class Backend:
 name='postgresql'
 @contextmanager
 def transaction(self):
  with psycopg.connect('',autocommit=False) as conn:yield conn
 @contextmanager
 def connect(self):
  with psycopg.connect('') as conn:yield conn

class CustomerPostgresConcurrencyTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with psycopg.connect('') as conn:
   conn.execute('CREATE TEMP TABLE sanity_check (id integer)')
   conn.execute('CREATE TABLE instance_update_state (instance_id TEXT PRIMARY KEY, active_job_id TEXT, state TEXT NOT NULL, updated_at TEXT)')
   conn.execute("INSERT INTO instance_update_state (instance_id,state) VALUES ('test-instance','update_available')")
 def test_concurrent_customer_updates(self):
  repo=ServerUpdateRepository(Backend());dispatched=[];lock=threading.Lock();barrier=threading.Barrier(2)
  def fake_queue(iid,*,requested_by,trigger_type):
   with lock:dispatched.append(iid)
   return {'run_id':'test-run'}
  repo.queue_update=fake_queue
  def call():
   barrier.wait()
   try:return repo.queue_customer_operation('test-instance',action='update',requested_by='test')
   except ValueError:return 'rejected'
  with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(lambda _:call(),range(2)))
  self.assertEqual(len(dispatched),1)
  self.assertEqual(results.count('rejected'),1)
  with psycopg.connect('') as conn:self.assertTrue(conn.execute("SELECT active_job_id FROM instance_update_state WHERE instance_id='test-instance'").fetchone()[0].startswith('reserved-'))

if __name__=='__main__':unittest.main()
