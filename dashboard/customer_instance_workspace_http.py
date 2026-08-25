#!/usr/bin/env python3
"""HTTP integration for Customer Instance Workspace v2."""
from __future__ import annotations
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
PREFIX="/api/customer/instance/workspace"
ROUTES={PREFIX,PREFIX+"/telemetry",PREFIX+"/console",PREFIX+"/startup",PREFIX+"/files/status",PREFIX+"/backup-policy",PREFIX+"/backups",PREFIX+"/upgrade-options",PREFIX+"/upgrade",PREFIX+"/runtime-options",PREFIX+"/permissions"}

def install_customer_instance_workspace(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST;previous_patch=getattr(legacy.DashboardHandler,"do_PATCH",None)
 legacy.STATIC_FILES.update({"/customer-instance.html":legacy.WEB_DIR/"customer-instance.html","/customer-instance-v2.js":legacy.WEB_DIR/"customer-instance-v2.js","/customer-instance-v2.css":legacy.WEB_DIR/"customer-instance-v2.css","/customer-backup-transfer.js":legacy.WEB_DIR/"customer-backup-transfer.js","/customer-instance-delete.js":legacy.WEB_DIR/"customer-instance-delete.js"})
 def service():return CustomerInstanceWorkspaceService(legacy.dashboard_repository(legacy.DATABASE_FILE).backend,legacy.DSM_ROOT)
 def user_for(self):
  value=session_user_from_headers(self.headers)
  if value is not None:return value
  try:return authenticate(self.headers)
  except Exception:return None
 def require_user(self):
  user=user_for(self)
  if user is None:self.unauthorized();return None
  if str(user.get("role") or "").lower() not in {"customer","admin","controller"}:self.forbidden();return None
  return user
 def one(parsed,name,default=None):return (parse_qs(parsed.query,keep_blank_values=True).get(name) or [default])[0]
 def iid(parsed,body=None):return str((body or {}).get("instance_id") or one(parsed,"instance_id","") or "").strip()
 def error(self,exc):
  if isinstance(exc,PermissionError):self.send_json(403,{"error":"forbidden","message":str(exc)});return
  if isinstance(exc,KeyError):self.send_json(404,{"error":"not_found","message":"Registro não encontrado."});return
  if isinstance(exc,(ValueError,LookupError)):self.send_json(400,{"error":"invalid_request","message":str(exc)});return
  self.send_json(500,{"error":"workspace_failed","message":"Não foi possível concluir a operação da instância."})
 def get(self):
  parsed=urlparse(self.path);path=parsed.path
  if path not in ROUTES:return previous_get(self)
  user=require_user(self)
  if user is None:return
  instance_id=iid(parsed)
  try:
   api=service()
   if path==PREFIX:data=api.overview(user,instance_id)
   elif path==PREFIX+"/telemetry":data={"samples":api.telemetry(user,instance_id,int(one(parsed,"limit",240) or 240))}
   elif path==PREFIX+"/console":data={"lines":api.console_output(user,instance_id,int(one(parsed,"limit",300) or 300))}
   elif path==PREFIX+"/startup":data=api.startup(user,instance_id)
   elif path==PREFIX+"/files/status":data=api.file_status(user,instance_id,one(parsed,"command_id",""))
   elif path==PREFIX+"/backup-policy":data=api.backup_policy(user,instance_id)
   elif path==PREFIX+"/backups":data={"jobs":api.backup_jobs(user,instance_id)}
   elif path==PREFIX+"/upgrade-options":data=api.upgrade_options(user,instance_id)
   elif path==PREFIX+"/runtime-options":data={"runtimes":api.runtime_options(user,instance_id)}
   elif path==PREFIX+"/permissions":data={"permissions":sorted(api.permissions(user,instance_id))}
   else:data={"changes":api.repo.list_contract_changes(instance_id)}
   self.send_json(200,data)
  except Exception as exc:error(self,exc)
 def post(self):
  parsed=urlparse(self.path);path=parsed.path
  if path not in {PREFIX+"/console",PREFIX+"/upgrade",PREFIX+"/files",PREFIX+"/backups"}:return previous_post(self)
  user=require_user(self)
  if user is None:return
  try:
   body=self.read_json_body();instance_id=iid(parsed,body);api=service()
   if path==PREFIX+"/console":data=api.send_console(user,instance_id,body.get("command"));code=202
   elif path==PREFIX+"/files":data=api.queue_file(user,instance_id,body.get("action"),path=body.get("path"),target_path=body.get("target_path"),payload=body.get("payload"));code=202
   elif path==PREFIX+"/backups":data=api.request_backup(user,instance_id,body.get("action"),body.get("backup_id"));code=202
   else:data=api.request_upgrade(user,instance_id,body.get("profile_id"));code=202
   self.send_json(code,data)
  except Exception as exc:error(self,exc)
 def patch(self):
  parsed=urlparse(self.path);path=parsed.path
  if path not in {PREFIX+"/startup",PREFIX+"/backup-policy"}:
   if previous_patch is not None:return previous_patch(self)
   self.send_json(404,{"error":"not_found"});return
  user=require_user(self)
  if user is None:return
  try:
   body=self.read_json_body();instance_id=iid(parsed,body);api=service();data=api.save_startup(user,instance_id,body.get("values")) if path.endswith("startup") else api.save_backup_policy(user,instance_id,body);self.send_json(200,data)
  except Exception as exc:error(self,exc)
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post;legacy.DashboardHandler.do_PATCH=patch

__all__=["PREFIX","ROUTES","install_customer_instance_workspace"]
