#!/usr/bin/env python3
"""HTTP dispatcher for Universal Smart Backup."""
from __future__ import annotations
from urllib.parse import parse_qs
from backup_api import list_jobs,list_policies,request_job,set_policy
from backup_platform import BackupValidationError
BACKUP_PATH="/api/backups"
def dispatch_backup_get(path,query,*,user,backend):
 if path!=BACKUP_PATH:return None
 try:
  q=parse_qs(query or "");kind=str((q.get("kind") or ["jobs"])[0]).lower()
  if kind=="policies":return 200,list_policies(user=user,backend=backend,agent_id=(q.get("agent_id") or [None])[0])
  return 200,list_jobs(user=user,backend=backend,instance_id=(q.get("instance_id") or [None])[0],agent_id=(q.get("agent_id") or [None])[0],status=(q.get("status") or [None])[0])
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except (ValueError,BackupValidationError) as exc:return 400,{"error":"invalid_request","message":str(exc)}
def dispatch_backup_post(path,payload,*,user,backend):
 if path!=BACKUP_PATH:return None
 try:
  body=dict(payload or {});operation=str(body.pop("operation","") or "").lower()
  if operation=="policy":return 200,set_policy(body,user=user,backend=backend)
  if operation in {"create","restore","delete"}:body["action"]=operation;return 202,request_job(body,user=user,backend=backend)
  return 400,{"error":"invalid_request","message":"operation must be policy, create, restore or delete"}
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except (ValueError,BackupValidationError) as exc:return 400,{"error":"invalid_request","message":str(exc)}
__all__=["BACKUP_PATH","dispatch_backup_get","dispatch_backup_post"]
