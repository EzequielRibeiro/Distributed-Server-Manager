#!/usr/bin/env python3
"""Backend-neutral persistence and delivery for D1 automation/broadcast."""
from __future__ import annotations
import json,sys,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any,Mapping
ROOT=Path(__file__).resolve().parents[1];CORE=ROOT/"core"
if str(CORE) not in sys.path:sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from automation_platform import AutomationValidationError,normalize_broadcast,normalize_rule
from event_platform import utc_now
class AutomationRepository:
 def __init__(self,backend):self.backend=backend
 def initialize(self):self.backend.initialize()
 @property
 def ph(self):return "?" if self.backend.name=="sqlite" else "%s"
 def _decode_rule(self,row):
  if row is None:return None
  v=dict(row)
  for col,name,default in (("trigger_json","trigger",{}),("conditions_json","conditions",[]),("actions_json","actions",[])):
   try:v[name]=json.loads(v.pop(col))
   except Exception:v[name]=default
  v["kind"]="CapivaraAutomationRule";v["schema_version"]=1;v["enabled"]=bool(v.get("enabled"));return v
 def get_rule(self,rule_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return self._decode_rule(s.execute(f"SELECT * FROM automation_rules WHERE rule_id={self.ph}",(rule_id,)).fetchone())
   finally:s.close()
 def put_rule(self,raw:Mapping[str,Any],*,requested_by=None):
  item=normalize_rule(raw);existing=self.get_rule(item["rule_id"])
  if existing and existing.get("checksum")==item["checksum"]:return {"rule":existing,"changed":False}
  rev=int(existing.get("revision") or 0)+1 if existing else 1;now=utc_now();trigger=json.dumps(item["trigger"],sort_keys=True,separators=(",",":"));conditions=json.dumps(item["conditions"],separators=(",",":"));actions=json.dumps(item["actions"],sort_keys=True,separators=(",",":"))
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    vals=(item["name"],1 if item["enabled"] else 0,trigger,conditions,actions,item["cooldown_seconds"],rev,item["checksum"],requested_by,now)
    if existing:s.execute(f"UPDATE automation_rules SET name={self.ph},enabled={self.ph},trigger_json={self.ph},conditions_json={self.ph},actions_json={self.ph},cooldown_seconds={self.ph},revision={self.ph},checksum={self.ph},requested_by={self.ph},updated_at={self.ph} WHERE rule_id={self.ph}",(*vals,item["rule_id"]))
    else:s.execute(f"INSERT INTO automation_rules(rule_id,name,enabled,trigger_json,conditions_json,actions_json,cooldown_seconds,revision,checksum,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*12)})",(item["rule_id"],*vals[:-1],now,now))
    s.execute(f"INSERT INTO automation_rule_revisions(rule_id,revision,name,enabled,trigger_json,conditions_json,actions_json,cooldown_seconds,checksum,requested_by,created_at) VALUES ({','.join([self.ph]*11)})",(item["rule_id"],rev,item["name"],1 if item["enabled"] else 0,trigger,conditions,actions,item["cooldown_seconds"],item["checksum"],requested_by,now))
   finally:s.close()
  return {"rule":self.get_rule(item["rule_id"]),"changed":True}
 def list_rules(self,limit=500):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [self._decode_rule(r) for r in s.execute(f"SELECT * FROM automation_rules ORDER BY rule_id LIMIT {self.ph}",(max(1,min(int(limit),2000)),)).fetchall()]
   finally:s.close()
 def history(self,rule_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    out=[]
    for r in s.execute(f"SELECT * FROM automation_rule_revisions WHERE rule_id={self.ph} ORDER BY revision DESC",(rule_id,)).fetchall():
     v=dict(r)
     for col,name,default in (("trigger_json","trigger",{}),("conditions_json","conditions",[]),("actions_json","actions",[])):
      try:v[name]=json.loads(v.pop(col))
      except Exception:v[name]=default
     out.append(v)
    return out
   finally:s.close()
 def _recipients(self,b):
  scope,target=b["scope"],b.get("target");sql="SELECT id,agent_id FROM instances";params=()
  if scope=="instance":sql+=f" WHERE id={self.ph}";params=(target,)
  elif scope=="agent":sql+=f" WHERE agent_id={self.ph}";params=(target,)
  elif scope=="game":sql+=f" WHERE game_id={self.ph}";params=(target,)
  elif scope=="customer":sql+=f" WHERE customer_id={self.ph}";params=(target,)
  elif scope=="datacenter":sql+=f" WHERE agent_id IN (SELECT agent_id FROM agent_locations WHERE datacenter_id={self.ph} AND status='active')";params=(target,)
  elif scope=="region":sql+=f" WHERE agent_id IN (SELECT al.agent_id FROM agent_locations al JOIN datacenters d ON d.id=al.datacenter_id WHERE d.region_id={self.ph} AND al.status='active' AND d.status='active')";params=(target,)
  elif scope!="global":raise AutomationValidationError("unsupported broadcast scope")
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [(str(r["id"]),str(r["agent_id"])) for r in s.execute(sql,params).fetchall() if r["agent_id"]]
   finally:s.close()
 def create_broadcast(self,raw:Mapping[str,Any],*,requested_by=None):
  b=normalize_broadcast(raw);bid=str(uuid.uuid4());now=datetime.now(timezone.utc);created=now.isoformat().replace("+00:00","Z");expires=(now+timedelta(seconds=b["ttl_seconds"])).isoformat().replace("+00:00","Z");recipients=self._recipients(b)
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    s.execute(f"INSERT INTO broadcasts(broadcast_id,scope,target,message,priority,ttl_seconds,require_ack,status,requested_by,created_at,expires_at) VALUES ({','.join([self.ph]*11)})",(bid,b["scope"],b.get("target"),b["message"],b["priority"],b["ttl_seconds"],1 if b["require_ack"] else 0,"pending" if recipients else "completed",requested_by,created,expires))
    for iid,aid in recipients:s.execute(f"INSERT INTO broadcast_deliveries(delivery_id,broadcast_id,agent_id,instance_id,status,attempts,updated_at) VALUES ({','.join([self.ph]*7)})",(str(uuid.uuid4()),bid,aid,iid,"pending",0,created))
   finally:s.close()
  return {"broadcast_id":bid,"recipients":len(recipients),**b,"created_at":created,"expires_at":expires}
 def list_broadcasts(self,limit=200):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [dict(r) for r in s.execute(f"SELECT * FROM broadcasts ORDER BY created_at DESC LIMIT {self.ph}",(max(1,min(int(limit),1000)),)).fetchall()]
   finally:s.close()
 def desired_for_agent(self,agent_id,limit=200):
  now=utc_now()
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    rows=s.execute(f"SELECT d.delivery_id,d.broadcast_id,d.instance_id,d.attempts,b.message,b.priority,b.ttl_seconds,b.require_ack,b.expires_at FROM broadcast_deliveries d JOIN broadcasts b ON b.broadcast_id=d.broadcast_id WHERE d.agent_id={self.ph} AND d.status IN ('pending','delivered') AND b.expires_at>{self.ph} ORDER BY CASE b.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,b.created_at LIMIT {self.ph}",(agent_id,now,max(1,min(int(limit),500)))).fetchall();return [dict(r) for r in rows]
   finally:s.close()
 def record_broadcast_state(self,agent_id,reports):
  accepted=0;now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    for raw in reports[:500]:
     did=str(raw.get("delivery_id") or "");status=str(raw.get("status") or "").lower()
     if not did or status not in {"delivered","acknowledged","failed"}:continue
     row=s.execute(f"SELECT delivery_id,broadcast_id FROM broadcast_deliveries WHERE delivery_id={self.ph} AND agent_id={self.ph}",(did,agent_id)).fetchone()
     if not row:continue
     delivered=raw.get("delivered_at") or (now if status in {"delivered","acknowledged"} else None);ack=raw.get("acknowledged_at") or (now if status=="acknowledged" else None)
     s.execute(f"UPDATE broadcast_deliveries SET status={self.ph},attempts=attempts+1,delivered_at=COALESCE(delivered_at,{self.ph}),acknowledged_at=COALESCE(acknowledged_at,{self.ph}),last_error={self.ph},updated_at={self.ph} WHERE delivery_id={self.ph}",(status,delivered,ack,raw.get("last_error"),now,did));accepted+=1
    s.execute("UPDATE broadcasts SET status='completed' WHERE status!='completed' AND NOT EXISTS (SELECT 1 FROM broadcast_deliveries d WHERE d.broadcast_id=broadcasts.broadcast_id AND d.status NOT IN ('acknowledged','failed'))")
   finally:s.close()
  return accepted
 def create_run(self,*,rule_id=None,trigger_type="manual",trigger_ref=None,context=None,requested_by=None,status="completed",result=None):
  rid=str(uuid.uuid4());now=utc_now();payload=json.dumps(context or {},sort_keys=True,separators=(",",":"));out=json.dumps(result or {},sort_keys=True,separators=(",",":"))
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:s.execute(f"INSERT INTO automation_runs(run_id,rule_id,trigger_type,trigger_ref,status,context_json,result_json,requested_by,started_at,completed_at,created_at,updated_at) VALUES ({','.join([self.ph]*12)})",(rid,rule_id,trigger_type,trigger_ref,status,payload,out,requested_by,now,now,now,now))
   finally:s.close()
  return rid
__all__=["AutomationRepository"]
