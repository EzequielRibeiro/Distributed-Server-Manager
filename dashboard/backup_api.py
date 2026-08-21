#!/usr/bin/env python3
"""Administrative service boundary for Universal Smart Backup."""
from __future__ import annotations
from typing import Any
from backup_repository import BackupRepository
from universal_event_repository import UniversalEventRepository
def _admin(user):
 actor=user if isinstance(user,dict) else {}
 if str(actor.get("role") or "").lower() not in {"admin","controller"}:raise PermissionError("administrator access required")
 return actor
def list_policies(*,user,backend,agent_id=None):
 _admin(user);r=BackupRepository(backend);r.initialize();rows=r.list_policies(agent_id=agent_id);return {"schema_version":1,"kind":"CapivaraBackupPolicyList","policies":rows,"count":len(rows)}
def list_jobs(*,user,backend,instance_id=None,agent_id=None,status=None):
 _admin(user);r=BackupRepository(backend);r.initialize();rows=r.list_jobs(instance_id=instance_id,agent_id=agent_id,status=status);return {"schema_version":1,"kind":"CapivaraBackupJobList","jobs":rows,"count":len(rows)}
def set_policy(payload:dict[str,Any]|None,*,user,backend):
 actor=_admin(user);r=BackupRepository(backend);r.initialize();result=r.put_policy(dict(payload or {}),requested_by=str(actor.get("username") or actor.get("id") or "admin"))
 if result["changed"]:
  p=result["policy"];e=UniversalEventRepository(backend);e.initialize();e.publish({"event_type":"BACKUP_POLICY_UPDATED","source":"controller.backup","severity":"info","actor_type":"dashboard_user","actor_id":str(actor.get("username") or "admin"),"agent_id":p.get("agent_id"),"instance_id":p.get("instance_id"),"data":{"policy_id":p["policy_id"],"revision":p["revision"],"enabled":p["enabled"],"mode":p["mode"],"consistency":p["consistency"]}})
 return result
def request_job(payload:dict[str,Any]|None,*,user,backend):
 actor=_admin(user);body=dict(payload or {});action=str(body.get("action") or "create").lower()
 if action not in {"create","restore","delete"}:raise ValueError("unsupported backup action")
 r=BackupRepository(backend);r.initialize();job=r.request(str(body.get("instance_id") or ""),action=action,backup_id=body.get("backup_id"),reason="manual",requested_by=str(actor.get("username") or actor.get("id") or "admin"));e=UniversalEventRepository(backend);e.initialize();e.publish({"event_type":"BACKUP_REQUESTED","source":"controller.backup","severity":"info","actor_type":"dashboard_user","actor_id":str(actor.get("username") or "admin"),"agent_id":job.get("agent_id"),"instance_id":job.get("instance_id"),"data":{"command_id":job["command_id"],"action":job["action"],"backup_id":job.get("backup_id")}});return job
__all__=["list_jobs","list_policies","request_job","set_policy"]
