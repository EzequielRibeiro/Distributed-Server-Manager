#!/usr/bin/env python3
"""Backend-neutral persistence and scheduling for Universal Smart Backup."""
from __future__ import annotations
import json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Mapping
ROOT=Path(__file__).resolve().parents[1];CORE=ROOT/"core"
if str(CORE) not in sys.path:sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from backup_platform import BackupValidationError,normalize_policy
from event_platform import utc_now

def _epoch(value:Any)->float:
 try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
 except Exception:return 0.0
class BackupRepository:
 def __init__(self,backend):self.backend=backend
 def initialize(self):self.backend.initialize()
 @property
 def ph(self):return "?" if self.backend.name=="sqlite" else "%s"
 def _instance(self,iid):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return s.execute(f"SELECT id,agent_id FROM instances WHERE id={self.ph}",(iid,)).fetchone()
   finally:s.close()
 def _policy(self,row):
  if row is None:return None
  v=dict(row);v["enabled"]=bool(v.get("enabled"))
  for col,name in (("include_json","include_paths"),("exclude_json","exclude_paths")):
   try:v[name]=json.loads(v.pop(col) or "[]")
   except Exception:v[name]=[]
  v["schema_version"]=1;v["kind"]="CapivaraBackupPolicy";return v
 def get_policy(self,instance_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return self._policy(s.execute(f"SELECT * FROM backup_policies WHERE instance_id={self.ph}",(instance_id,)).fetchone())
   finally:s.close()
 def put_policy(self,raw:Mapping[str,Any],*,requested_by=None):
  iid=str((raw or {}).get("instance_id") or "").strip();inst=self._instance(iid)
  if inst is None:raise BackupValidationError("instance does not exist")
  aid=str(dict(inst).get("agent_id") or "");body=dict(raw or {});body["agent_id"]=aid;item=normalize_policy(body,expected_agent_id=aid);old=self.get_policy(iid)
  if old and old.get("checksum")==item["checksum"]:return {"policy":old,"changed":False}
  pid=str(old["policy_id"]) if old else str(uuid.uuid4());rev=int(old.get("revision") or 0)+1 if old else 1;now=utc_now();inc=json.dumps(item["include_paths"],separators=(",",":"));exc=json.dumps(item["exclude_paths"],separators=(",",":"))
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    vals=(item["agent_id"],1 if item["enabled"] else 0,item["mode"],item["consistency"],item["compression"],item["interval_seconds"],item["retention_count"],inc,exc,rev,item["checksum"],requested_by,now)
    if old:s.execute(f"UPDATE backup_policies SET agent_id={self.ph},enabled={self.ph},mode={self.ph},consistency={self.ph},compression={self.ph},interval_seconds={self.ph},retention_count={self.ph},include_json={self.ph},exclude_json={self.ph},revision={self.ph},checksum={self.ph},requested_by={self.ph},updated_at={self.ph} WHERE policy_id={self.ph}",(*vals,pid))
    else:s.execute(f"INSERT INTO backup_policies(policy_id,instance_id,agent_id,enabled,mode,consistency,compression,interval_seconds,retention_count,include_json,exclude_json,revision,checksum,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*16)})",(pid,iid,*vals,now))
    s.execute(f"INSERT INTO backup_policy_revisions(policy_id,revision,enabled,mode,consistency,compression,interval_seconds,retention_count,include_json,exclude_json,checksum,requested_by,created_at) VALUES ({','.join([self.ph]*13)})",(pid,rev,1 if item["enabled"] else 0,item["mode"],item["consistency"],item["compression"],item["interval_seconds"],item["retention_count"],inc,exc,item["checksum"],requested_by,now))
   finally:s.close()
  return {"policy":self.get_policy(iid),"changed":True}
 def list_policies(self,*,agent_id=None,limit=500):
  where="";params=[]
  if agent_id:where=f" WHERE agent_id={self.ph}";params.append(agent_id)
  params.append(max(1,min(int(limit),2000)))
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [self._policy(r) for r in s.execute(f"SELECT * FROM backup_policies{where} ORDER BY instance_id LIMIT {self.ph}",tuple(params)).fetchall()]
   finally:s.close()
 def history(self,policy_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [dict(r) for r in s.execute(f"SELECT * FROM backup_policy_revisions WHERE policy_id={self.ph} ORDER BY revision DESC",(policy_id,)).fetchall()]
   finally:s.close()
 def request(self,instance_id,*,action="create",backup_id=None,reason="manual",requested_by=None):
  inst=self._instance(instance_id)
  if inst is None:raise BackupValidationError("instance does not exist")
  aid=str(dict(inst).get("agent_id") or "");policy=self.get_policy(instance_id);cid=str(uuid.uuid4());now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:s.execute(f"INSERT INTO backup_jobs(command_id,backup_id,instance_id,agent_id,action,policy_revision,status,reason,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*11)})",(cid,backup_id,instance_id,aid,action,int(policy.get("revision")) if policy else None,"pending",reason,requested_by,now,now))
   finally:s.close()
  return self.get_job(cid)
 def get_job(self,command_id):
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:
    r=s.execute(f"SELECT * FROM backup_jobs WHERE command_id={self.ph}",(command_id,)).fetchone();return dict(r) if r else None
   finally:s.close()
 def list_jobs(self,*,instance_id=None,agent_id=None,status=None,limit=500):
  clauses=[];params=[]
  for col,val in (("instance_id",instance_id),("agent_id",agent_id),("status",status)):
   if val:clauses.append(f"{col}={self.ph}");params.append(val)
  where=" WHERE "+" AND ".join(clauses) if clauses else "";params.append(max(1,min(int(limit),2000)))
  with self.backend.connect() as c:
   s=AlertSession(self.backend,c)
   try:return [dict(r) for r in s.execute(f"SELECT * FROM backup_jobs{where} ORDER BY created_at DESC LIMIT {self.ph}",tuple(params)).fetchall()]
   finally:s.close()
 def schedule_due(self,agent_id,*,now_epoch=None):
  now_epoch=float(now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp());created=[]
  for p in self.list_policies(agent_id=agent_id):
   if not p["enabled"]:continue
   jobs=self.list_jobs(instance_id=p["instance_id"],limit=50)
   if any(j["status"] in {"pending","running"} for j in jobs):continue
   last=max((_epoch(j.get("completed_at")) for j in jobs if j.get("action")=="create" and j.get("status")=="completed"),default=0)
   if last and now_epoch-last<int(p["interval_seconds"]):continue
   created.append(self.request(p["instance_id"],action="create",reason="schedule",requested_by="scheduler"))
  return created
 def commands_for_agent(self,agent_id):
  self.schedule_due(agent_id);out=[]
  for j in reversed(self.list_jobs(agent_id=agent_id,status="pending",limit=100)):
   p=self.get_policy(j["instance_id"])
   out.append({"schema_version":1,"kind":"CapivaraBackupCommand","command_id":j["command_id"],"action":j["action"],"instance_id":j["instance_id"],"agent_id":agent_id,"backup_id":j.get("backup_id"),"reason":j.get("reason"),"policy":p or {},"requested_by":j.get("requested_by")})
  return out
 def record_agent_state(self,agent_id,reports:list[Mapping[str,Any]]):
  accepted=0;now=utc_now()
  with self.backend.transaction() as c:
   s=AlertSession(self.backend,c)
   try:
    for r in reports[:500]:
     cid=str(r.get("command_id") or "");row=s.execute(f"SELECT * FROM backup_jobs WHERE command_id={self.ph} AND agent_id={self.ph}",(cid,agent_id)).fetchone()
     if not row:continue
     status=str(r.get("status") or "failed").lower()
     if status not in {"running","completed","failed"}:continue
     backup_id=r.get("backup_id") or dict(row).get("backup_id")
     s.execute(f"UPDATE backup_jobs SET backup_id={self.ph},status={self.ph},size_bytes={self.ph},sha256={self.ph},artifact_path={self.ph},started_at={self.ph},completed_at={self.ph},last_error={self.ph},updated_at={self.ph} WHERE command_id={self.ph}",(backup_id,status,r.get("size_bytes"),r.get("sha256"),r.get("artifact_path"),r.get("started_at") or (now if status=="running" else None),r.get("completed_at") or (now if status in {"completed","failed"} else None),r.get("last_error"),now,cid));accepted+=1
   finally:s.close()
  return accepted
__all__=["BackupRepository"]
