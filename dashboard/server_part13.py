#!/usr/bin/env python3
"""Agent administration, runtime orchestration and universal platform HTTP composition."""
from __future__ import annotations
import time
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import server_part12 as integration
from agent_game_data_http import GAME_DATA_JOBS_PATH,GAME_DATA_OPERATION_PATH,LEGACY_ENVIRONMENT_INSTALL_PATH,dispatch_agent_game_data_get,dispatch_agent_game_data_post
from agent_instance_provisioning_http import INSTANCE_PROVISIONING_PATH,dispatch_instance_provisioning_get,dispatch_instance_provisioning_post
from agent_instance_runtime_http import INSTANCE_RUNTIME_PATH,dispatch_instance_runtime_get,dispatch_instance_runtime_post
from agent_update_http import CHANNEL_PATH,ROLLOUT_PATH,STATUS_PATH,dispatch_update_get,dispatch_update_post
from api_access_http import API_TOKENS_PATH,dispatch_api_access_get,dispatch_api_access_post
from api_access_repository import ApiAccessRepository
from automation_http import AUTOMATION_PATH,BROADCAST_PATH,dispatch_automation_get,dispatch_automation_post
from backup_http import BACKUP_PATH,dispatch_backup_get,dispatch_backup_post
from configuration_http import CONFIGURATIONS_PATH,dispatch_configuration_get,dispatch_configuration_post
from content_http import CONTENT_PATH,dispatch_content_get,dispatch_content_post
from customer_admin_api import CUSTOMER_ADMIN_GET_PATHS,CUSTOMER_ADMIN_POST_PATHS,dispatch_customer_admin_get,dispatch_customer_admin_post
from customer_admin_repository import CustomerAdminRepository
from customer_invitation_api import PUBLIC_INVITATION_PATHS,TEAM_INVITATION_PATHS,dispatch_customer_invitations
from customer_team_api import CUSTOMER_TEAM_PATHS,dispatch_customer_team
from controller_session import session_user_from_headers
from ha_dr_http import HA_DR_PATH,dispatch_ha_get,dispatch_ha_post
from infrastructure_role_http import INFRASTRUCTURE_ROLE_PATH,dispatch_infrastructure_role_get,dispatch_infrastructure_role_post
from observability_http import OBSERVABILITY_PATH,dispatch_observability_get
from realtime_http import PUBLIC_GET_PATHS,PUBLIC_POST_PATHS,SSE_EVENTS_PATH,dispatch_realtime_get,dispatch_realtime_post,serve_event_stream
from universal_event_http import EVENTS_PATH,dispatch_universal_event_get,dispatch_universal_event_post
legacy=integration.legacy;_previous_get=legacy.DashboardHandler.do_GET;_previous_post=legacy.DashboardHandler.do_POST;_authenticate=integration._authenticate
ROOT_DIR=Path(__file__).resolve().parents[1];WINDOWS_INSTALL_PATH="/agent/install.ps1";WINDOWS_INSTALL_FILE=ROOT_DIR/"agents"/"windows"/"installer"/"bootstrap-release.ps1";VERSION_FILE=ROOT_DIR/"version"
legacy.STATIC_FILES["/agent-updates.js"]=legacy.WEB_DIR/"agent-updates.js";legacy.STATIC_FILES["/infrastructure-role-ui.js"]=legacy.WEB_DIR/"infrastructure-role-ui.js";legacy.STATIC_FILES["/game-data-orchestration.js"]=legacy.WEB_DIR/"game-data-orchestration.js"
CUSTOMER_ADMIN_FILES={"/customers.html":legacy.WEB_DIR/"customers.html","/customers.js":legacy.WEB_DIR/"customers.js","/customer-admin.html":legacy.WEB_DIR/"customer-admin.html","/customer-admin.js":legacy.WEB_DIR/"customer-admin.js","/customer-admin.css":legacy.WEB_DIR/"customer-admin.css","/customer-change-password.html":legacy.WEB_DIR/"customer-change-password.html","/customer-change-password.js":legacy.WEB_DIR/"customer-change-password.js"}
CUSTOMER_TEAM_FILES={"/customer-members.html":legacy.WEB_DIR/"customer-members.html","/customer-members.js":legacy.WEB_DIR/"customer-members.js","/customer-team.css":legacy.WEB_DIR/"customer-team.css"}
CUSTOMER_PASSWORD_GATED_PAGES={"/customer.html","/customer-members.html","/customer-instance.html"}
legacy.STATIC_FILES.update(CUSTOMER_ADMIN_FILES);legacy.STATIC_FILES.update(CUSTOMER_TEAM_FILES)
def _user(self):
 user=_authenticate(self.headers)
 if user is None:self.unauthorized()
 return user
def _backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
def _redirect(self,location):
 self.send_response(302);self.send_header("Location",location);self.send_header("Cache-Control","no-store");self.send_header("Content-Length","0");self.end_headers()
def _api_principal(self):
 authorization=str(self.headers.get("Authorization") or "")
 if not authorization.lower().startswith("bearer "):
  self.send_json(401,{"error":"unauthorized","message":"Bearer API token required"});return None
 try:
  r=ApiAccessRepository(_backend());r.initialize();return r.authenticate(authorization.split(None,1)[1])
 except Exception:
  self.send_json(401,{"error":"unauthorized","message":"Invalid or expired API token"});return None
def _audit_api(principal,self,status,started):
 try:
  r=ApiAccessRepository(_backend());r.initialize();remote=self.client_address[0] if getattr(self,"client_address",None) else None;r.record_request(token_id=principal.get("token_id") if principal else None,method=self.command,path=urlparse(self.path).path,status_code=status,latency_ms=(time.monotonic()-started)*1000,remote_address=remote)
 except Exception:pass
def _serve_windows_bootstrap(self):
 try:script=WINDOWS_INSTALL_FILE.read_text(encoding="utf-8");version=VERSION_FILE.read_text(encoding="utf-8").strip()
 except OSError:self.send_error(404);return
 prefix=f'$env:CAPIVARA_RELEASE_TAG = if ($env:CAPIVARA_RELEASE_TAG) {{ $env:CAPIVARA_RELEASE_TAG }} else {{ "v{version}" }}\r\n';body=(prefix+script).encode();self.send_response(200);self.send_header("Content-Type","text/plain; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
def _require_session_page(self,path):
 user=session_user_from_headers(self.headers)
 if user is None:
  _redirect(self,"/customer-login.html" if path in {"/customer-change-password.html","/customer-members.html"} else "/login.html");return None
 allowed={"customer"} if path in {"/customer-change-password.html","/customer-members.html"} else {"admin","controller","operator"}
 if user.get("role") not in allowed:self.forbidden();return None
 return user
def _require_customer_password_rotation(self,path):
 if path not in CUSTOMER_PASSWORD_GATED_PAGES:return True
 user=session_user_from_headers(self.headers)
 if user is None:return True
 if user.get("role")!="customer":return True
 try:required=CustomerAdminRepository(_backend()).password_change_required(str(user.get("username") or ""))
 except Exception:required=False
 if required:_redirect(self,"/customer-change-password.html");return False
 return True
def _customer_api_user(self):
 user=_user(self)
 if user is None:return None
 if user.get("role")!="customer":self.forbidden();return None
 return user
def integrated_get(self):
 parsed=urlparse(self.path);path=parsed.path
 if not _require_customer_password_rotation(self,path):return
 if path in {"/customers.html","/customer-admin.html","/customer-change-password.html","/customer-members.html"}:
  if _require_session_page(self,path) is None:return
  source=CUSTOMER_TEAM_FILES.get(path) or CUSTOMER_ADMIN_FILES[path];self.send_file(source);return
 if path in set(CUSTOMER_ADMIN_FILES)|set(CUSTOMER_TEAM_FILES):
  self.send_file((CUSTOMER_TEAM_FILES.get(path) or CUSTOMER_ADMIN_FILES[path]));return
 if path in CUSTOMER_ADMIN_GET_PATHS:
  user=_user(self)
  if user is None:return
  status,body=dispatch_customer_admin_get(path,parse_qs(parsed.query),user=user,backend=_backend());self.send_json(status,body);return
 if path in CUSTOMER_TEAM_PATHS:
  user=_customer_api_user(self)
  if user is None:return
  result=dispatch_customer_team("GET",path,payload=None,user=user,backend=_backend())
  if result is not None:status,body=result;self.send_json(status,body);return
 if path in TEAM_INVITATION_PATHS:
  user=_customer_api_user(self)
  if user is None:return
  result=dispatch_customer_invitations("GET",path,payload=None,user=user,backend=_backend())
  if result is not None:status,body=result;self.send_json(status,body);return
 if path==WINDOWS_INSTALL_PATH:return _serve_windows_bootstrap(self)
 if path in PUBLIC_GET_PATHS or path==SSE_EVENTS_PATH:
  started=time.monotonic();principal=_api_principal(self)
  if principal is None:return
  if path==SSE_EVENTS_PATH:
   serve_event_stream(self,parsed.query,principal=principal,backend=_backend());_audit_api(principal,self,200,started);return
  status,body=dispatch_realtime_get(path,parsed.query,principal=principal,backend=_backend());self.send_json(status,body);_audit_api(principal,self,status,started);return
 if path==API_TOKENS_PATH:
  user=_user(self)
  if user is None:return
  status,body=dispatch_api_access_get(path,parsed.query,user=user,backend=_backend());self.send_json(status,body);return
 if path in {AUTOMATION_PATH,BROADCAST_PATH,BACKUP_PATH,CONFIGURATIONS_PATH,CONTENT_PATH,OBSERVABILITY_PATH,EVENTS_PATH,GAME_DATA_JOBS_PATH,INSTANCE_PROVISIONING_PATH,INSTANCE_RUNTIME_PATH,INFRASTRUCTURE_ROLE_PATH,HA_DR_PATH}:
  user=_user(self)
  if user is None:return
  if path in {AUTOMATION_PATH,BROADCAST_PATH}:status,body=dispatch_automation_get(path,parsed.query,user=user,backend=_backend())
  elif path==BACKUP_PATH:status,body=dispatch_backup_get(path,parsed.query,user=user,backend=_backend())
  elif path==CONFIGURATIONS_PATH:status,body=dispatch_configuration_get(path,parsed.query,user=user,backend=_backend())
  elif path==CONTENT_PATH:status,body=dispatch_content_get(path,parsed.query,user=user,backend=_backend())
  elif path==OBSERVABILITY_PATH:status,body=dispatch_observability_get(path,parsed.query,user=user,backend=_backend())
  elif path==EVENTS_PATH:status,body=dispatch_universal_event_get(path,parsed.query,user=user,backend=_backend())
  elif path==GAME_DATA_JOBS_PATH:status,body=dispatch_agent_game_data_get(path,parsed.query,user=user,backend=_backend())
  elif path==INSTANCE_PROVISIONING_PATH:status,body=dispatch_instance_provisioning_get(path,parsed.query,user=user,backend=_backend())
  elif path==INSTANCE_RUNTIME_PATH:status,body=dispatch_instance_runtime_get(path,parsed.query,user=user,backend=_backend())
  elif path==HA_DR_PATH:status,body=dispatch_ha_get(path,parse_qs(parsed.query),user=user,backend=_backend())
  else:
   query=parse_qs(parsed.query);status,body=dispatch_infrastructure_role_get(path,user=user,backend=_backend(),node_id=(query.get("node_id") or [None])[0])
  self.send_json(status,body);return
 if path!=STATUS_PATH:return _previous_get(self)
 user=_user(self)
 if user is None:return
 query=parse_qs(parsed.query);status,body=dispatch_update_get(path,user=user,backend=_backend(),agent_id=(query.get("agent_id") or [None])[0]);self.send_json(status,body)
def _payload(self):
 try:return self.read_json_body(),None
 except ValueError:return None,{"error":"invalid_request","message":"Requisição inválida."}
def integrated_post(self):
 parsed=urlparse(self.path);path=parsed.path
 if path in PUBLIC_INVITATION_PATHS:
  payload,error=_payload(self)
  if error:self.send_json(400,error);return
  result=dispatch_customer_invitations("POST",path,payload=payload,user=None,backend=_backend())
  if result is not None:status,body=result;self.send_json(status,body);return
 if path in CUSTOMER_TEAM_PATHS or path in TEAM_INVITATION_PATHS:
  user=_customer_api_user(self)
  if user is None:return
  payload,error=_payload(self)
  if error:self.send_json(400,error);return
  result=(dispatch_customer_team("POST",path,payload=payload,user=user,backend=_backend()) if path in CUSTOMER_TEAM_PATHS else dispatch_customer_invitations("POST",path,payload=payload,user=user,backend=_backend()))
  if result is not None:status,body=result;self.send_json(status,body);return
 if path in CUSTOMER_ADMIN_POST_PATHS:
  user=_user(self)
  if user is None:return
  payload,error=_payload(self)
  if error:self.send_json(400,error);return
  status,body=dispatch_customer_admin_post(path,payload,user=user,backend=_backend());self.send_json(status,body);return
 if path in PUBLIC_POST_PATHS:
  started=time.monotonic();principal=_api_principal(self)
  if principal is None:return
  payload,error=_payload(self)
  if error:self.send_json(400,error);_audit_api(principal,self,400,started);return
  status,body=dispatch_realtime_post(path,payload,principal=principal,backend=_backend());self.send_json(status,body);_audit_api(principal,self,status,started);return
 if path==API_TOKENS_PATH:
  user=_user(self)
  if user is None:return
  payload,error=_payload(self)
  if error:self.send_json(400,error);return
  status,body=dispatch_api_access_post(path,payload,user=user,backend=_backend());self.send_json(status,body);return
 if path in {AUTOMATION_PATH,BROADCAST_PATH,BACKUP_PATH,CONFIGURATIONS_PATH,CONTENT_PATH,EVENTS_PATH,GAME_DATA_OPERATION_PATH,LEGACY_ENVIRONMENT_INSTALL_PATH,INSTANCE_PROVISIONING_PATH,INSTANCE_RUNTIME_PATH,INFRASTRUCTURE_ROLE_PATH,HA_DR_PATH}:
  user=_user(self)
  if user is None:return
  payload,error=_payload(self)
  if error:self.send_json(400,error);return
  if path in {AUTOMATION_PATH,BROADCAST_PATH}:status,body=dispatch_automation_post(path,payload,user=user,backend=_backend())
  elif path==BACKUP_PATH:status,body=dispatch_backup_post(path,payload,user=user,backend=_backend())
  elif path==CONFIGURATIONS_PATH:status,body=dispatch_configuration_post(path,payload,user=user,backend=_backend())
  elif path==CONTENT_PATH:status,body=dispatch_content_post(path,payload,user=user,backend=_backend())
  elif path==EVENTS_PATH:status,body=dispatch_universal_event_post(path,payload,user=user,backend=_backend())
  elif path in {GAME_DATA_OPERATION_PATH,LEGACY_ENVIRONMENT_INSTALL_PATH}:status,body=dispatch_agent_game_data_post(path,payload,user=user,backend=_backend(),root=ROOT_DIR)
  elif path==INSTANCE_PROVISIONING_PATH:status,body=dispatch_instance_provisioning_post(path,payload,user=user,backend=_backend())
  elif path==INSTANCE_RUNTIME_PATH:status,body=dispatch_instance_runtime_post(path,payload,user=user,backend=_backend())
  elif path==HA_DR_PATH:status,body=dispatch_ha_post(path,payload,user=user,backend=_backend())
  else:status,body=dispatch_infrastructure_role_post(path,payload,user=user,backend=_backend(),root=ROOT_DIR)
  self.send_json(status,body);return
 if path not in {ROLLOUT_PATH,CHANNEL_PATH}:return _previous_post(self)
 user=_user(self)
 if user is None:return
 payload,error=_payload(self)
 if error:self.send_json(400,error);return
 status,body=dispatch_update_post(path,payload,user=user,backend=_backend());self.send_json(status,body)
legacy.DashboardHandler.do_GET=integrated_get;legacy.DashboardHandler.do_POST=integrated_post
def run():legacy.run()
if __name__=="__main__":run()
