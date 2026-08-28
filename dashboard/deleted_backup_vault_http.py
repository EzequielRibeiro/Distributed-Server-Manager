#!/usr/bin/env python3
"""Customer HTTP surface for distributed instance deletion and retained backups."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from customer_reference import resolve_customer_reference
from deleted_backup_vault_repository import DeletedBackupVaultRepository
LIST_PATH="/api/customer/deleted-backups";DOWNLOAD_PATH=LIST_PATH+"/download";REMOVE_BACKUP_PATH=LIST_PATH+"/delete";DELETE_PATH="/api/customer/instance/delete";STATUS_PATH=DELETE_PATH+"/status"
def install_deleted_backup_vault_http(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST;root=Path(legacy.DSM_ROOT)
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def vault():return DeletedBackupVaultRepository(backend(),root)
 def workspace():return CustomerInstanceWorkspaceService(backend(),root)
 def actor(self):
  value=session_user_from_headers(self.headers, area="customer")
  if value is not None:return value
  try:return authenticate(self.headers)
  except Exception:return None
 def customer(self):
  user=actor(self)
  if user is None:self.unauthorized();return None
  if str(user.get("role") or "").lower()!="customer":self.forbidden();return None
  try:customer_id=resolve_customer_reference(user.get("scope_id"),public_only=isinstance(user.get("scope_id"),str))
  except (TypeError,ValueError):self.forbidden();return None
  return user,customer_id
 def one(parsed,name,default=""):return (parse_qs(parsed.query,keep_blank_values=True).get(name) or [default])[0]
 def public_item(item):return {k:item.get(k) for k in ("vault_id","source_instance_id","source_instance_name","game_id","runtime_id","backup_id","status","size_bytes","sha256","created_at","expires_at","deleted_at","downloaded_at","last_error")}
 def get(self):
  parsed=urlparse(self.path);path=parsed.path
  if path not in {LIST_PATH,DOWNLOAD_PATH,STATUS_PATH}:return previous_get(self)
  resolved=customer(self)
  if resolved is None:return
  _,customer_id=resolved
  try:
   if path==LIST_PATH:return self.send_json(200,{"backups":[public_item(x) for x in vault().list_for_customer(customer_id)]})
   vault_id=str(one(parsed,"vault_id") or "").strip()
   if path==STATUS_PATH:
    item=vault().reconcile(vault_id)
    if int(item.get("customer_id") or 0)!=customer_id:raise PermissionError("vault belongs to another Customer")
    return self.send_json(200,public_item(item))
   artifact,item=vault().artifact_for_customer(vault_id,customer_id);size=artifact.stat().st_size;name=Path(str(item.get("source_instance_name") or item.get("source_instance_id") or "server")).name+"-final-backup"+(".tar.gz" if artifact.name.endswith((".gz",".tgz")) else ".tar")
   self.send_response(200);self.send_header("Content-Type","application/octet-stream");self.send_header("Content-Disposition",f'attachment; filename="{name.replace(chr(34),"")}"');self.send_header("Content-Length",str(size));self.send_header("Cache-Control","no-store");self.end_headers();sent=0
   with artifact.open("rb") as source:
    while True:
     chunk=source.read(1024*1024)
     if not chunk:break
     self.wfile.write(chunk);sent+=len(chunk)
   self.wfile.flush()
   if sent==size:vault().complete_download(vault_id,customer_id)
  except (BrokenPipeError,ConnectionResetError):return
  except PermissionError:return self.send_json(403,{"error":"forbidden"})
  except (KeyError,FileNotFoundError):return self.send_json(404,{"error":"backup_not_ready"})
  except (ValueError,OSError) as exc:return self.send_json(400,{"error":"invalid_request","message":str(exc)})
 def post(self):
  parsed=urlparse(self.path);path=parsed.path
  if path not in {DELETE_PATH,REMOVE_BACKUP_PATH}:return previous_post(self)
  resolved=customer(self)
  if resolved is None:return
  user,customer_id=resolved
  try:
   body=self.read_json_body()
   if path==REMOVE_BACKUP_PATH:
    vault_id=str(body.get("vault_id") or "").strip()
    if not vault_id:raise ValueError("vault_id is required")
    item=vault().delete_for_customer(vault_id,customer_id);return self.send_json(200,{"deleted":True,"vault":public_item(item)})
   instance_id=str(body.get("instance_id") or "").strip();context=workspace().require(user,instance_id,"instance.delete");expected=str(context.get("name") or context.get("id") or "").strip();confirmation=str(body.get("confirmation") or "").strip()
   if not confirmation or confirmation not in {expected,str(context.get("id") or "")}:raise ValueError("Digite o nome ou ID da instância para confirmar a exclusão.")
   final_backup=bool(body.get("final_backup",True));requested_by=str(user.get("username") or "customer")
   if final_backup:
    workspace().require(user,instance_id,"backup.create");workspace().require(user,instance_id,"backup.download");item,idempotent=vault().start(instance_id,requested_by=requested_by,retention_hours=168);return self.send_json(202,{"mode":"backup_then_remove","vault":public_item(item),"idempotent":idempotent})
   command=AgentInstanceRuntimeRepository(backend()).enqueue(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,action="remove",requested_by=requested_by);return self.send_json(202,{"mode":"remove","command_id":command.get("command_id"),"status":command.get("status")})
  except PermissionError:return self.send_json(403,{"error":"forbidden"})
  except KeyError:return self.send_json(404,{"error":"not_found"})
  except ValueError as exc:return self.send_json(400,{"error":"invalid_request","message":str(exc)})
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post
__all__=["LIST_PATH","DOWNLOAD_PATH","REMOVE_BACKUP_PATH","DELETE_PATH","STATUS_PATH","install_deleted_backup_vault_http"]
