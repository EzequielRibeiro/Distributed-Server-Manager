#!/usr/bin/env python3
"""Customer Workspace HTTP surface for Universal Content."""
from __future__ import annotations
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from customer_content_workspace import CustomerContentWorkspaceService
from instance_activity_repository import InstanceActivityRepository
from json_serialization import to_json_compatible

PATH="/api/customer/instance/workspace/content"

def install_customer_content_http(legacy,authenticate):
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
  if isinstance(exc,KeyError):return send(self,404,{"error":"not_found","message":"Conteúdo não encontrado."})
  if isinstance(exc,(ValueError,LookupError)):return send(self,400,{"error":"invalid_request","message":str(exc)})
  internal=getattr(self,"_internal_error",None)
  if callable(internal):return internal(exc)
  return send(self,500,{"error":"content_failed","message":"Não foi possível concluir a operação de conteúdo."})
 def record(user,instance_id,action,content_id,result):
  try:
   api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT);context=api.workspace.repo.instance_context(instance_id)
   InstanceActivityRepository(backend()).record(instance_id=instance_id,customer_id=context.get("customer_id"),username=str(user.get("username") or ""),role=str(user.get("role") or ""),activity=f"CONTENT_{action.upper()}_REQUESTED",category="content",result="accepted",target_type="content",target_name=content_id,details={"changed":bool(result.get("changed")),"revision":(result.get("assignment") or {}).get("revision")})
  except Exception:pass
 def get(self):
  parsed=urlparse(self.path)
  if parsed.path!=PATH:return previous_get(self)
  user=require_user(self)
  if user is None:return
  try:send(self,200,{"content":CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT).list(user,iid(parsed))})
  except Exception as exc:error(self,exc)
 def post(self):
  parsed=urlparse(self.path)
  if parsed.path!=PATH:return previous_post(self)
  user=require_user(self)
  if user is None:return
  try:
   body=self.read_json_body();instance_id=iid(parsed,body);action=str(body.get("action") or "install").strip().lower();api=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT)
   if action=="install":result=api.install(user,instance_id,body)
   else:
    content_id=str(body.get("content_id") or "").strip()
    if not content_id:raise ValueError("content_id is required")
    result=api.mutate(user,instance_id,content_id,action,body)
   record(user,instance_id,action,str((result.get("assignment") or {}).get("content_id") or body.get("content_id") or ""),result);send(self,202,result)
  except Exception as exc:error(self,exc)
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post

__all__=["PATH","install_customer_content_http"]
