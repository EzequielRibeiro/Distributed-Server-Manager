#!/usr/bin/env python3
"""Backend-neutral desired-state persistence for Universal Content."""
from __future__ import annotations
import json,sys,uuid
from pathlib import Path
from typing import Any,Mapping
ROOT=Path(__file__).resolve().parents[1]; CORE=ROOT/"core"
if str(CORE) not in sys.path: sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from content_platform import ContentValidationError,normalize_assignment
from event_platform import utc_now

class ContentRepository:
 def __init__(self,backend): self.backend=backend
 def initialize(self): self.backend.initialize()
 @property
 def ph(self): return "?" if self.backend.name=="sqlite" else "%s"
 def _row(self,row):
  if row is None:return None
  v=dict(row)
  for col,name,default in (("artifact_json","artifact",{}),("dependencies_json","dependencies",[]),("conflicts_json","conflicts",[])):
   try:v[name]=json.loads(v.pop(col))
   except (TypeError,json.JSONDecodeError):v[name]=default
  v["kind"]="CapivaraContentAssignment";v["schema_version"]=1
  return v
 def _instance(self,instance_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return s.execute(f"SELECT id,agent_id,game_id FROM instances WHERE id={self.ph}",(instance_id,)).fetchone()
   finally:s.close()
 def get(self,instance_id,content_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return self._row(s.execute(f"SELECT * FROM content_assignments WHERE instance_id={self.ph} AND content_id={self.ph}",(instance_id,content_id)).fetchone())
   finally:s.close()
 def put(self,raw:Mapping[str,Any],*,requested_by:str|None=None):
  body=dict(raw or {}); instance_id=str(body.get("instance_id") or "").strip(); inst=self._instance(instance_id)
  if inst is None: raise ContentValidationError("instance does not exist")
  agent_id=str(dict(inst)["agent_id"] or "").strip(); game_id=str(dict(inst).get("game_id") or body.get("game_id") or "").strip()
  body["agent_id"]=agent_id; body["game_id"]=game_id
  item=normalize_assignment(body,expected_agent_id=agent_id); existing=self.get(item["instance_id"],item["content_id"])
  if existing and existing.get("checksum")==item["checksum"]: return {"assignment":existing,"changed":False}
  aid=str(existing["assignment_id"]) if existing else str(uuid.uuid4()); rev=int(existing.get("revision") or 0)+1 if existing else 1
  now=utc_now(); artifact=json.dumps(item["artifact"],sort_keys=True,separators=(",",":"),ensure_ascii=False); deps=json.dumps(item["dependencies"],separators=(",",":")); conflicts=json.dumps(item["conflicts"],separators=(",",":"))
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    vals=(item["agent_id"],item["game_id"],item["content_type"],item["desired_state"],item["version"],item["provider"],item["target"],artifact,deps,conflicts,rev,item["checksum"],requested_by,now)
    if existing:
     s.execute(f"UPDATE content_assignments SET agent_id={self.ph},game_id={self.ph},content_type={self.ph},desired_state={self.ph},version={self.ph},provider={self.ph},target={self.ph},artifact_json={self.ph},dependencies_json={self.ph},conflicts_json={self.ph},revision={self.ph},checksum={self.ph},requested_by={self.ph},updated_at={self.ph} WHERE assignment_id={self.ph}",(*vals,aid))
    else:
     s.execute(f"INSERT INTO content_assignments(assignment_id,instance_id,agent_id,content_id,game_id,content_type,desired_state,version,provider,target,artifact_json,dependencies_json,conflicts_json,revision,checksum,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*18)})",(aid,item["instance_id"],item["agent_id"],item["content_id"],item["game_id"],item["content_type"],item["desired_state"],item["version"],item["provider"],item["target"],artifact,deps,conflicts,rev,item["checksum"],requested_by,now,now))
    s.execute(f"INSERT INTO content_assignment_revisions(assignment_id,revision,desired_state,version,provider,target,artifact_json,dependencies_json,conflicts_json,checksum,requested_by,created_at) VALUES ({','.join([self.ph]*12)})",(aid,rev,item["desired_state"],item["version"],item["provider"],item["target"],artifact,deps,conflicts,item["checksum"],requested_by,now))
   finally:s.close()
  return {"assignment":self.get(item["instance_id"],item["content_id"]),"changed":True}
 def list(self,*,agent_id=None,instance_id=None,desired_state=None,limit=500):
  clauses=[];params=[]
  for col,val in (("agent_id",agent_id),("instance_id",instance_id),("desired_state",desired_state)):
   if val:clauses.append(f"{col}={self.ph}");params.append(val)
  where=" WHERE "+" AND ".join(clauses) if clauses else "";params.append(max(1,min(int(limit),2000)))
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [self._row(r) for r in s.execute(f"SELECT * FROM content_assignments{where} ORDER BY instance_id,content_id LIMIT {self.ph}",tuple(params)).fetchall()]
   finally:s.close()
 def history(self,assignment_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    out=[]
    for row in s.execute(f"SELECT * FROM content_assignment_revisions WHERE assignment_id={self.ph} ORDER BY revision DESC",(assignment_id,)).fetchall():
     v=dict(row)
     for col,name,default in (("artifact_json","artifact",{}),("dependencies_json","dependencies",[]),("conflicts_json","conflicts",[])):
      try:v[name]=json.loads(v.pop(col))
      except Exception:v[name]=default
     out.append(v)
    return out
   finally:s.close()
 def _applied(self,agent_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return {(str(r["instance_id"]),str(r["content_id"])):(int(r["applied_revision"] or 0),str(r["applied_checksum"] or ""),str(r["status"] or "")) for r in s.execute(f"SELECT * FROM agent_content_state WHERE agent_id={self.ph}",(agent_id,)).fetchall()}
   finally:s.close()
 def desired_for_agent(self,agent_id):
  applied=self._applied(agent_id);out=[]
  for a in self.list(agent_id=agent_id,limit=2000):
   state=applied.get((a["instance_id"],a["content_id"]))
   if state==(int(a["revision"]),str(a["checksum"]),"applied"):continue
   out.append(a)
  return out
 def record_agent_state(self,agent_id,reports:list[Mapping[str,Any]]):
  accepted=0;now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    for r in reports[:2000]:
     iid=str(r.get("instance_id") or "");cid=str(r.get("content_id") or "")
     inst=self._instance(iid)
     if not inst or str(dict(inst)["agent_id"] or "")!=agent_id or not cid:continue
     desired_rev=int(r.get("desired_revision") or r.get("applied_revision") or 0);desired_sum=str(r.get("desired_checksum") or r.get("applied_checksum") or "")
     if not desired_rev or not desired_sum:continue
     existing=s.execute(f"SELECT agent_id FROM agent_content_state WHERE agent_id={self.ph} AND instance_id={self.ph} AND content_id={self.ph}",(agent_id,iid,cid)).fetchone()
     vals=(desired_rev,int(r.get("applied_revision") or 0) or None,desired_sum,str(r.get("applied_checksum") or "") or None,str(r.get("status") or "unknown"),r.get("installed_version"),r.get("last_error"),r.get("reported_at") or now,now)
     if existing:s.execute(f"UPDATE agent_content_state SET desired_revision={self.ph},applied_revision={self.ph},desired_checksum={self.ph},applied_checksum={self.ph},status={self.ph},installed_version={self.ph},last_error={self.ph},reported_at={self.ph},updated_at={self.ph} WHERE agent_id={self.ph} AND instance_id={self.ph} AND content_id={self.ph}",(*vals,agent_id,iid,cid))
     else:s.execute(f"INSERT INTO agent_content_state(agent_id,instance_id,content_id,desired_revision,applied_revision,desired_checksum,applied_checksum,status,installed_version,last_error,reported_at,updated_at) VALUES ({','.join([self.ph]*12)})",(agent_id,iid,cid,*vals))
     accepted+=1
   finally:s.close()
  return accepted

__all__=["ContentRepository"]
