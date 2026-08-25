#!/usr/bin/env python3
"""HTTP integration for Customer Instance Workspace v2."""
from __future__ import annotations
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from instance_activity_repository import InstanceActivityRepository
PREFIX="/api/customer/instance/workspace"
ROUTES={PREFIX,PREFIX+"/telemetry",PREFIX+"/console",PREFIX+"/startup",PREFIX+"/files/status",PREFIX+"/backup-policy",PREFIX+"/backups",PREFIX+"/upgrade-options",PREFIX+"/upgrade",PREFIX+"/runtime-options",PREFIX+"/permissions"}
_FILE_ACTIVITY={"write_text":"FILE_EDIT_REQUESTED","upload":"FILE_UPLOAD_REQUESTED","delete":"FILE_DELETE_REQUESTED","move":"FILE_MOVE_REQUESTED","rename":"FILE_RENAME_REQUESTED","mkdir":"DIRECTORY_CREATE_REQUESTED","extract":"ARCHIVE_EXTRACT_REQUESTED","download":"FILE_DOWNLOAD_REQUESTED"}

def install_customer_instance_workspace(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST;previous_patch=getattr(legacy.DashboardHandler,"do_PATCH",None)
 legacy.STATIC_FILES.update({"/customer-instance.html":legacy.WEB_DIR/"customer-instance.html","/customer-instance-v2.js":legacy.WEB_DIR/"customer-instance-v2.js","/customer-instance-v2.css":legacy.WEB_DIR/"customer-instance-v2.css","/customer-backup-transfer.js":legacy.WEB_DIR/"customer-backup-transfer.js","/customer-instance-delete.js":legacy.WEB_DIR/"customer-instance-delete.js","/customer-instance-activity.js":legacy.WEB_DIR/"customer-instance-activity.js"})
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def service():return CustomerInstanceWorkspaceService(backend(),legacy.DSM_ROOT)
 def activity_repo():return InstanceActivityRepository(backend())
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
 def record(api,user,instance_id,activity,category,*,target_type=None,target_name=None,details=None,result="accepted"):
  try:
   context=api.repo.instance_context(instance_id)
   activity_repo().record(instance_id=instance_id,customer_id=context.get("customer_id"),username=str(user.get("username") or ""),role=str(user.get("role") or ""),activity=activity,category=category,result=result,target_type=target_type,target_name=target_name,details=details)
  except Exception:pass
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
   if path==PREFIX+"/console":
    data=api.send_console(user,instance_id,body.get("command"));code=202;record(api,user,instance_id,"CONSOLE_COMMAND_REQUESTED","console",details={"command_id":data.get("command_id")})
   elif path==PREFIX+"/files":
    action=str(body.get("action") or "").lower();data=api.queue_file(user,instance_id,action,path=body.get("path"),target_path=body.get("target_path"),payload=body.get("payload"));code=202
    semantic=_FILE_ACTIVITY.get(action)
    if semantic:record(api,user,instance_id,semantic,"files",target_type="file",target_name=body.get("path"),details={"command_id":data.get("command_id"),"target_path":body.get("target_path")})
   elif path==PREFIX+"/backups":
    action=str(body.get("action") or "").lower();data=api.request_backup(user,instance_id,action,body.get("backup_id"));code=202;record(api,user,instance_id,f"BACKUP_{action.upper()}_REQUESTED","backup",target_type="backup",target_name=body.get("backup_id"),details={"job_id":data.get("job_id") or data.get("command_id")})
   else:
    data=api.request_upgrade(user,instance_id,body.get("profile_id"));code=202;record(api,user,instance_id,"CONTRACT_UPGRADE_REQUESTED","contract",target_type="resource_profile",target_name=body.get("profile_id"),details={"request_id":data.get("request_id")})
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
   body=self.read_json_body();instance_id=iid(parsed,body);api=service()
   if path.endswith("startup"):
    data=api.save_startup(user,instance_id,body.get("values"));record(api,user,instance_id,"STARTUP_CONFIGURATION_CHANGED","configuration",details={"fields":sorted((body.get("values") or {}).keys())},result="success")
   else:
    data=api.save_backup_policy(user,instance_id,body);record(api,user,instance_id,"BACKUP_SCHEDULE_CHANGED","backup",details={"enabled":bool(body.get("enabled",True)),"schedule_time":body.get("schedule_time"),"schedule_timezone":body.get("schedule_timezone")},result="success")
   self.send_json(200,data)
  except Exception as exc:error(self,exc)
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post;legacy.DashboardHandler.do_PATCH=patch

__all__=["PREFIX","ROUTES","install_customer_instance_workspace"]
