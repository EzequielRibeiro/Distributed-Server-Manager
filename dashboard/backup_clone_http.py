#!/usr/bin/env python3
"""Customer-visible status surface for durable create-from-backup orchestration."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from customer_reference import resolve_customer_reference
from instance_backup_clone_repository import InstanceBackupCloneRepository
PREFIX="/api/customer/backup-clones";STATUS=PREFIX+"/status"
def install_backup_clone_http(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;root=Path(legacy.DSM_ROOT)
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def actor(self):
  user=session_user_from_headers(self.headers, area="customer")
  if user is not None:return user
  try:return authenticate(self.headers)
  except Exception:return None
 def public(item):return {k:item.get(k) for k in ("clone_id","source_vault_id","target_instance_id","target_agent_id","provisioning_id","transfer_id","imported_backup_id","restore_job_id","status","last_error","created_at","completed_at","updated_at")}
 def get(self):
  parsed=urlparse(self.path)
  if parsed.path not in {PREFIX,STATUS}:return previous_get(self)
  user=actor(self)
  if user is None:return self.unauthorized()
  role=str(user.get("role") or "").lower();repo=InstanceBackupCloneRepository(backend(),root);repo.initialize()
  try:
   if parsed.path==STATUS:
    clone_id=str((parse_qs(parsed.query).get("clone_id") or [""])[0]).strip()
    if not clone_id:raise ValueError("clone_id is required")
    item=repo.reconcile(clone_id)
    if role=="customer":
     cid=resolve_customer_reference(user.get("scope_id"),public_only=isinstance(user.get("scope_id"),str))
     if int(item.get("customer_id") or 0)!=cid:raise PermissionError("backup clone belongs to another Customer")
    elif role not in {"admin","controller"}:raise PermissionError("forbidden")
    return self.send_json(200,public(item))
   if role=="customer":
    cid=resolve_customer_reference(user.get("scope_id"),public_only=isinstance(user.get("scope_id"),str));items=repo.list_for_customer(cid)
   elif role in {"admin","controller"}:
    items=[]
    for active in repo.list_active():items.append(active)
   else:raise PermissionError("forbidden")
   return self.send_json(200,{"clones":[public(item) for item in items]})
  except PermissionError:return self.send_json(403,{"error":"forbidden"})
  except KeyError:return self.send_json(404,{"error":"not_found"})
  except ValueError as exc:return self.send_json(400,{"error":"invalid_request","message":str(exc)})
 legacy.DashboardHandler.do_GET=get
__all__=["PREFIX","STATUS","install_backup_clone_http"]
