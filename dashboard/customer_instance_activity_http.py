#!/usr/bin/env python3
"""Customer-facing per-instance activity timeline and semantic action recording."""
from __future__ import annotations
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from instance_activity_repository import InstanceActivityRepository

PREFIX="/api/customer/instance/activity"
OPTIONS=PREFIX+"/options"
ACTION=PREFIX+"/action"

_ACTIONS={
 "start":("INSTANCE_STARTED","server","instance.start"),
 "stop":("INSTANCE_STOPPED","server","instance.stop"),
 "restart":("INSTANCE_RESTARTED","server","instance.restart"),
}

def install_customer_instance_activity(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def service():return CustomerInstanceWorkspaceService(backend(),legacy.DSM_ROOT)
 def repo():return InstanceActivityRepository(backend())
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
 def error(self,exc):
  if isinstance(exc,PermissionError):self.send_json(403,{"error":"forbidden","message":str(exc)});return
  if isinstance(exc,(ValueError,LookupError)):self.send_json(400,{"error":"invalid_request","message":str(exc)});return
  self.send_json(500,{"error":"activity_failed","message":"Não foi possível consultar a atividade da instância."})
 def get(self):
  parsed=urlparse(self.path)
  if parsed.path not in {PREFIX,OPTIONS}:return previous_get(self)
  user=require_user(self)
  if user is None:return
  instance_id=str(one(parsed,"instance_id","") or "").strip()
  try:
   service().require(user,instance_id,"activity.read")
   if parsed.path==OPTIONS:self.send_json(200,repo().options(instance_id));return
   try:limit=int(one(parsed,"limit",200) or 200)
   except ValueError:limit=200
   rows=repo().search(instance_id=instance_id,username=one(parsed,"username"),category=one(parsed,"category"),activity=one(parsed,"activity"),result=one(parsed,"result"),start_at=one(parsed,"start_at"),end_at=one(parsed,"end_at"),limit=limit)
   self.send_json(200,{"activities":rows})
  except Exception as exc:error(self,exc)
 def post(self):
  parsed=urlparse(self.path)
  if parsed.path!=ACTION:return previous_post(self)
  user=require_user(self)
  if user is None:return
  try:
   body=self.read_json_body();instance_id=str(body.get("instance_id") or "").strip();action=str(body.get("action") or "").strip().lower()
   spec=_ACTIONS.get(action)
   if spec is None:raise ValueError("unsupported instance activity action")
   activity,category,permission=spec;context=service().require(user,instance_id,permission)
   event_id=repo().record(instance_id=instance_id,customer_id=context.get("customer_id"),username=str(user.get("username") or ""),role=str(user.get("role") or ""),activity=activity,category=category,result=str(body.get("result") or "success"),details={"source":"customer_workspace"})
   self.send_json(201,{"event_id":event_id})
  except Exception as exc:error(self,exc)
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post

__all__=["ACTION","OPTIONS","PREFIX","install_customer_instance_activity"]
