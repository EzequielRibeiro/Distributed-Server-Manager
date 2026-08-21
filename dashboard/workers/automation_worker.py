#!/usr/bin/env python3
"""D1 controller worker: consume C1 events, C3 metrics and schedule triggers."""
from __future__ import annotations
import json,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
for path in (ROOT/"core",ROOT/"database"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from alert_repository import AlertSession
from automation_engine import AutomationEngine
from automation_execution_repository import AutomationExecutionRepository
from automation_repository import AutomationRepository
from runtime_backend import backend_from_environment

def _field_matches(expr,value):
 expr=str(expr).strip()
 if expr=="*":return True
 for part in expr.split(","):
  part=part.strip()
  if part.startswith("*/"):
   try:return value%int(part[2:])==0
   except Exception:return False
  if "-" in part:
   try:
    lo,hi=(int(x) for x in part.split("-",1))
    if lo<=value<=hi:return True
   except Exception:return False
  else:
   try:
    if int(part)==value:return True
   except Exception:return False
 return False
def cron_matches(expression,when):
 fields=str(expression or "").split()
 if len(fields)!=5:return False
 minute,hour,day,month,weekday=fields;cron_weekday=(when.weekday()+1)%7
 return _field_matches(minute,when.minute) and _field_matches(hour,when.hour) and _field_matches(day,when.day) and _field_matches(month,when.month) and _field_matches(weekday,cron_weekday)
class AutomationWorker:
 def __init__(self,backend):
  self.backend=backend;self.repo=AutomationRepository(backend);self.repo.initialize();self.engine=AutomationEngine(backend);self.state=AutomationExecutionRepository(backend);self.ph="?" if backend.name=="sqlite" else "%s"
 def _event_batch(self,limit=200):
  cursor=self.state.state_get("event_cursor",{"received_at":"","event_id":""}) or {};received=str(cursor.get("received_at") or "");eid=str(cursor.get("event_id") or "")
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    if received:rows=s.execute(f"SELECT * FROM universal_events WHERE received_at>{self.ph} OR (received_at={self.ph} AND event_id>{self.ph}) ORDER BY received_at,event_id LIMIT {self.ph}",(received,received,eid,limit)).fetchall()
    else:rows=s.execute(f"SELECT * FROM universal_events ORDER BY received_at,event_id LIMIT {self.ph}",(limit,)).fetchall()
    return [dict(r) for r in rows]
   finally:s.close()
 def process_events(self):
  count=0
  for row in self._event_batch():
   try:data=json.loads(row.get("data_json") or "{}")
   except Exception:data={}
   context={"event_type":row.get("event_type"),"event_id":row.get("event_id"),"agent_id":row.get("agent_id"),"instance_id":row.get("instance_id"),"severity":row.get("severity"),"source":row.get("source"),"actor_id":row.get("actor_id"),"data":data}
   self.engine.fire("event",context,trigger_ref=str(row.get("event_id")),requested_by="automation-worker")
   self.state.state_set("event_cursor",{"received_at":row.get("received_at"),"event_id":row.get("event_id")});count+=1
  return count
 def process_metrics(self):
  count=0
  for rule in self.repo.list_rules(limit=2000):
   trigger=rule.get("trigger") or {}
   if not rule.get("enabled") or trigger.get("type")!="metric":continue
   metric=str(trigger.get("metric_name") or "")
   with self.backend.connect() as c:
    s=AlertSession(self.backend,c)
    try:rows=s.execute(f"SELECT * FROM observability_latest WHERE metric_name={self.ph} ORDER BY updated_at DESC LIMIT {self.ph}",(metric,500)).fetchall()
    finally:s.close()
   for raw in rows:
    row=dict(raw);context={"metric_name":metric,"value":row.get("value_double"),"agent_id":row.get("agent_id"),"subject_key":row.get("subject_key"),"sample_id":row.get("sample_id"),"unit":row.get("unit")}
    runs=self.engine.fire("metric",context,trigger_ref=str(row.get("sample_id")),requested_by="automation-worker");count+=sum(1 for r in runs if r.get("status") not in {"duplicate","cooldown"})
  return count
 def process_schedules(self,when=None):
  now=when or datetime.now(timezone.utc);minute_ref=now.strftime("%Y-%m-%dT%H:%MZ");count=0
  for rule in self.repo.list_rules(limit=2000):
   trigger=rule.get("trigger") or {}
   if not rule.get("enabled") or trigger.get("type")!="schedule" or not cron_matches(trigger.get("expression"),now):continue
   result=self.engine.execute_rule(rule,trigger_type="schedule",trigger_ref=minute_ref,context={"scheduled_at":minute_ref},requested_by="automation-worker")
   if result.get("status") not in {"duplicate","cooldown"}:count+=1
  return count
 def tick(self):return {"events":self.process_events(),"metrics":self.process_metrics(),"schedules":self.process_schedules()}
def run_forever(interval=5):
 backend=backend_from_environment();worker=AutomationWorker(backend)
 while True:
  try:worker.tick()
  except Exception as exc:print(f"automation worker failed: {exc}",file=sys.stderr,flush=True)
  time.sleep(max(1,int(interval)))
if __name__=="__main__":run_forever()
