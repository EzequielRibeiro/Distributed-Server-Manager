#!/usr/bin/env python3
"""Idempotent automation run claims and durable worker cursors."""
from __future__ import annotations
import json,uuid
from alert_repository import AlertSession
from event_platform import utc_now
class AutomationExecutionRepository:
 def __init__(self,backend):self.backend=backend
 @property
 def ph(self):return "?" if self.backend.name=="sqlite" else "%s"
 def claim(self,*,rule_id,trigger_type,trigger_ref=None,context=None,requested_by=None):
  run_id=str(uuid.uuid4());now=utc_now();payload=json.dumps(context or {},sort_keys=True,separators=(",",":"))
  try:
   with self.backend.transaction() as c:
    s=AlertSession(self.backend,c)
    try:s.execute(f"INSERT INTO automation_runs(run_id,rule_id,trigger_type,trigger_ref,status,context_json,result_json,requested_by,started_at,created_at,updated_at) VALUES ({','.join([self.ph]*11)})",(run_id,rule_id,trigger_type,trigger_ref,"running",payload,"{}",requested_by,now,now,now))
    finally:s.close()
  except Exception:
   if trigger_ref:
    with self.backend.connect() as c:
     s=AlertSession(self.backend,c)
     try:
      row=s.execute(f"SELECT run_id FROM automation_runs WHERE rule_id={self.ph} AND trigger_type={self.ph} AND trigger_ref={self.ph}",(rule_id,trigger_type,trigger_ref)).fetchone()
      if row:return None
     finally:s.close()
   raise
  return run_id
 def finish(self,run_id,*,status,result):
  now=utc_now();payload=json.dumps(result or {},sort_keys=True,separators=(",",":"))
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:s.execute(f"UPDATE automation_runs SET status={self.ph},result_json={self.ph},completed_at={self.ph},updated_at={self.ph} WHERE run_id={self.ph}",(status,payload,now,now,run_id))
   finally:s.close()
 def state_get(self,key,default=None):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    row=s.execute(f"SELECT state_value FROM automation_runtime_state WHERE state_key={self.ph}",(key,)).fetchone()
    if not row:return default
    try:return json.loads(dict(row)["state_value"])
    except Exception:return default
   finally:s.close()
 def state_set(self,key,value):
  now=utc_now();payload=json.dumps(value,sort_keys=True,separators=(",",":"))
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    row=s.execute(f"SELECT state_key FROM automation_runtime_state WHERE state_key={self.ph}",(key,)).fetchone()
    if row:s.execute(f"UPDATE automation_runtime_state SET state_value={self.ph},updated_at={self.ph} WHERE state_key={self.ph}",(payload,now,key))
    else:s.execute(f"INSERT INTO automation_runtime_state(state_key,state_value,updated_at) VALUES ({','.join([self.ph]*3)})",(key,payload,now))
   finally:s.close()
__all__=["AutomationExecutionRepository"]
