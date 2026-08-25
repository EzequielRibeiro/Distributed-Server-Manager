#!/usr/bin/env python3
"""Granular instance-team HTTP surface."""
from __future__ import annotations
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from instance_team_repository import InstanceTeamRepository
from instance_workspace_policy import INSTANCE_PERMISSIONS
from instance_workspace_repository import InstanceWorkspaceRepository

TEAM_PATH="/api/customer/instance/workspace/team";TEAM_INVITE_PATH=TEAM_PATH+"/invite";TEAM_GRANTS_PATH=TEAM_PATH+"/grants";TEAM_REMOVE_PATH=TEAM_PATH+"/remove";SHARED_PATH="/api/customer/shared-instances"

def install_customer_instance_team(legacy,authenticate):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST;previous_patch=getattr(legacy.DashboardHandler,"do_PATCH",None)
 def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
 def actor(self):
  value=session_user_from_headers(self.headers)
  if value is not None:return value
  try:return authenticate(self.headers)
  except Exception:return None
 def iid(parsed,body=None):return str((body or {}).get("instance_id") or (parse_qs(parsed.query).get("instance_id") or [""])[0]).strip()
 def require_owner(user,instance_id):
  if user is None:raise PermissionError("authentication required")
  if str(user.get("role") or "").lower() in {"admin","controller"}:return
  if str(user.get("role") or "").lower()!="customer":raise PermissionError("customer access required")
  repository=InstanceWorkspaceRepository(backend());context=repository.instance_context(instance_id);ph=repository.dialect.placeholder
  from alert_repository import AlertSession
  with backend().connect() as c:
   s=AlertSession(backend(),c)
   try:row=s.execute(f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",(int(context["customer_id"]),str(user.get("username") or "").lower())).fetchone()
   finally:s.close()
  if row is None or str(row["account_role"])!="owner":raise PermissionError("only the Customer owner can manage the instance team")
 def error(self,exc):
  if isinstance(exc,PermissionError):self.send_json(403,{"error":"forbidden","message":str(exc)})
  elif isinstance(exc,KeyError):self.send_json(404,{"error":"not_found"})
  elif isinstance(exc,(ValueError,LookupError)):self.send_json(400,{"error":"invalid_request","message":str(exc)})
  else:self.send_json(500,{"error":"team_failed","message":"Não foi possível administrar a equipe."})
 def get(self):
  parsed=urlparse(self.path);user=actor(self)
  if parsed.path==SHARED_PATH:
   if user is None:return self.unauthorized()
   if str(user.get("role") or "").lower()!="customer":return self.forbidden()
   try:self.send_json(200,{"instances":InstanceTeamRepository(backend()).shared_instances(str(user.get("username") or ""))})
   except Exception as exc:error(self,exc)
   return
  if parsed.path!=TEAM_PATH:return previous_get(self)
  instance_id=iid(parsed)
  try:require_owner(user,instance_id);repo=InstanceTeamRepository(backend());self.send_json(200,{"members":repo.members(instance_id),"available_permissions":sorted(INSTANCE_PERMISSIONS)})
  except Exception as exc:error(self,exc)
 def post(self):
  parsed=urlparse(self.path)
  if parsed.path not in {TEAM_INVITE_PATH,TEAM_REMOVE_PATH}:return previous_post(self)
  user=actor(self)
  try:
   body=self.read_json_body();instance_id=iid(parsed,body);require_owner(user,instance_id);repo=InstanceTeamRepository(backend())
   if parsed.path==TEAM_INVITE_PATH:data=repo.invite(instance_id=instance_id,email=body.get("email"),grants=body.get("grants") or {},invited_by=str(user.get("username") or ""));self.send_json(201,data)
   else:data=repo.remove_access(instance_id=instance_id,username=body.get("username"),removed_by=str(user.get("username") or ""));self.send_json(200,data)
  except Exception as exc:error(self,exc)
 def patch(self):
  parsed=urlparse(self.path)
  if parsed.path!=TEAM_GRANTS_PATH:
   if previous_patch is not None:return previous_patch(self)
   self.send_json(404,{"error":"not_found"});return
  user=actor(self)
  try:
   body=self.read_json_body();instance_id=iid(parsed,body);require_owner(user,instance_id);data=InstanceTeamRepository(backend()).set_grants(instance_id=instance_id,username=body.get("username"),grants=body.get("grants") or {},changed_by=str(user.get("username") or ""));self.send_json(200,data)
  except Exception as exc:error(self,exc)
 legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post;legacy.DashboardHandler.do_PATCH=patch

__all__=["TEAM_PATH","TEAM_INVITE_PATH","TEAM_GRANTS_PATH","TEAM_REMOVE_PATH","SHARED_PATH","install_customer_instance_team"]
