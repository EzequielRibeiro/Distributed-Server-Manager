#!/usr/bin/env python3
"""Cursor-based read model for D2 real-time consumers."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1];CORE=ROOT/"core"
if str(CORE) not in sys.path:sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from api_platform import decode_cursor,encode_cursor

class RealtimeRepository:
 def __init__(self,backend):self.backend=backend
 def initialize(self):self.backend.initialize()
 @property
 def ph(self):return "?" if self.backend.name=="sqlite" else "%s"
 def events(self,*,cursor=None,limit=100,event_type=None,agent_id=None,instance_id=None,severity=None):
  after=decode_cursor(cursor);clauses=[];params=[]
  if after:
   clauses.append(f"(occurred_at>{self.ph} OR (occurred_at={self.ph} AND event_id>{self.ph}))");params.extend([after[0],after[0],after[1]])
  for col,val in (("event_type",event_type.upper() if event_type else None),("agent_id",agent_id),("instance_id",instance_id),("severity",severity.lower() if severity else None)):
   if val is not None:clauses.append(f"{col}={self.ph}");params.append(val)
  where=" WHERE "+" AND ".join(clauses) if clauses else "";bounded=max(1,min(int(limit),500));params.append(bounded)
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:rows=s.execute(f"SELECT * FROM universal_events{where} ORDER BY occurred_at ASC,event_id ASC LIMIT {self.ph}",tuple(params)).fetchall()
   finally:s.close()
  items=[]
  for row in rows:
   item=dict(row)
   try:item["data"]=json.loads(item.pop("data_json") or "{}")
   except Exception:item["data"]={}
   item["kind"]="CapivaraUniversalEvent";items.append(item)
  next_cursor=encode_cursor(items[-1]["occurred_at"],items[-1]["event_id"]) if items else cursor
  return {"schema_version":1,"kind":"CapivaraRealtimeEventPage","events":items,"count":len(items),"cursor":next_cursor,"has_more":len(items)==bounded}
 def latest_observability(self,*,agent_id=None,instance_id=None,metric_name=None,limit=500):
  clauses=[];params=[]
  if agent_id:clauses.append(f"agent_id={self.ph}");params.append(agent_id)
  if instance_id:clauses.append(f"subject_key={self.ph}");params.append("instance:"+str(instance_id))
  if metric_name:clauses.append(f"metric_name={self.ph}");params.append(metric_name)
  where=" WHERE "+" AND ".join(clauses) if clauses else "";params.append(max(1,min(int(limit),1000)))
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:rows=s.execute(f"SELECT * FROM observability_latest{where} ORDER BY updated_at DESC LIMIT {self.ph}",tuple(params)).fetchall()
   finally:s.close()
  out=[]
  for row in rows:
   item=dict(row)
   try:item["dimensions"]=json.loads(item.pop("dimensions_json") or "{}")
   except Exception:item["dimensions"]={}
   out.append(item)
  return {"schema_version":1,"kind":"CapivaraObservabilityLatest","samples":out,"count":len(out)}
 def instances(self,*,agent_id=None,customer_id=None,game_id=None,limit=500):
  clauses=[];params=[]
  for col,val in (("agent_id",agent_id),("customer_id",customer_id),("game_id",game_id)):
   if val:clauses.append(f"{col}={self.ph}");params.append(val)
  where=" WHERE "+" AND ".join(clauses) if clauses else "";params.append(max(1,min(int(limit),1000)))
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:rows=s.execute(f"SELECT id,name,game_id,status,controller_id,agent_id,customer_id,node_id FROM instances{where} ORDER BY id LIMIT {self.ph}",tuple(params)).fetchall()
   finally:s.close()
  return {"schema_version":1,"kind":"CapivaraInstanceList","instances":[dict(x) for x in rows],"count":len(rows)}
 def status(self):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    events=s.execute("SELECT COUNT(*) AS n FROM universal_events").fetchone();tokens=s.execute("SELECT COUNT(*) AS n FROM api_tokens WHERE status='active'").fetchone();latest=s.execute("SELECT COUNT(*) AS n FROM observability_latest").fetchone()
   finally:s.close()
  return {"schema_version":1,"kind":"CapivaraRealtimeApiStatus","events":int(events["n"]),"active_api_tokens":int(tokens["n"]),"latest_metrics":int(latest["n"]),"transport":["rest","sse"],"api_version":"v1"}

__all__=["RealtimeRepository"]
