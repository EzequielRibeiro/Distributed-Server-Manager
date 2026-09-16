#!/usr/bin/env python3
"""Customer Workspace HTTP surface for scheduled maintenance."""
from __future__ import annotations
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from customer_maintenance_workspace import CustomerMaintenanceWorkspaceService
from instance_activity_repository import InstanceActivityRepository
from json_serialization import to_json_compatible

PATH="/api/customer/instance/workspace/maintenance"


def install_customer_maintenance_http(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def send(self,status,payload):return self.send_json(status,to_json_compatible(payload))
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
 def iid(parsed,body=None):return str((body or {}).get("instance_id") or (parse_qs(parsed.query,keep_blank_values=True).get("instance_id") or [""])[0] or "").strip()
 def error(self,exc):
  if isinstance(exc,PermissionError):return send(self,403,{"error":"forbidden","message":str(exc)})
  if isinstance(exc,KeyError):return send(self,404,{"error":"instance_not_found","message":"Instância não encontrada."})
  if isinstance(exc,RuntimeError):return send(self,409,{"error":"maintenance_busy","message":str(exc)})
  if isinstance(exc,(ValueError,LookupError)):return send(self,400,{"error":"invalid_request","message":str(exc)})
  internal=getattr(self,"_internal_error",None)
  if callable(internal):return internal(exc)
  return send(self,500,{"error":"maintenance_failed","message":"Não foi possível concluir a operação de manutenção."})
 def record(user,instance_id,result):
  try:
   service=CustomerMaintenanceWorkspaceService(backend(),legacy.DSM_ROOT);context=service.workspace.repo.instance_context(instance_id);policy=result.get("policy") if isinstance(result,dict) else {}
   InstanceActivityRepository(backend()).record(instance_id=instance_id,customer_id=context.get("customer_id"),username=str(user.get("username") or ""),role=str(user.get("role") or ""),activity="MAINTENANCE_POLICY_UPDATED",category="maintenance",result="success",target_type="instance",target_name=instance_id,details={"enabled":bool((policy or {}).get("enabled")),"schedule_mode":(policy or {}).get("schedule_mode"),"timezone":(policy or {}).get("timezone"),"coalesce_updates":bool((policy or {}).get("coalesce_updates"))})
  except Exception:pass
 def get(self):
  parsed=urlparse(self.path)
  if parsed.path!=PATH:return previous_get(self)
  user=require_user(self)
  if user is None:return
  try:return send(self,200,CustomerMaintenanceWorkspaceService(backend(),legacy.DSM_ROOT).view(user,iid(parsed)))
  except Exception as exc:return error(self,exc)
 def post(self):
  parsed=urlparse(self.path)
  if parsed.path!=PATH:return previous_post(self)
  user=require_user(self)
  if user is None:return
  try:
   body=self.read_json_body();instance_id=iid(parsed,body);result=CustomerMaintenanceWorkspaceService(backend(),legacy.DSM_ROOT).save(user,instance_id,body);record(user,instance_id,result);return send(self,200,result)
  except Exception as exc:return error(self,exc)
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post


__all__=["PATH","install_customer_maintenance_http"]
