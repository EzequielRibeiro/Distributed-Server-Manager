#!/usr/bin/env python3
"""Customer HTTP integration wrapper for Capivara DSM."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import server as legacy
from customer_account_http import AUTHENTICATED_PATHS,PUBLIC_PATHS,dispatch_customer_account
from customer_auth_api import CUSTOMER_AUTH_PATHS,dispatch_customer_auth
from customer_http_auth import authenticate_customer
from customer_invitation_api import PUBLIC_INVITATION_PATHS,TEAM_INVITATION_PATHS,dispatch_customer_invitations
from customer_rbac import instance_profile as customer_instance_profile,may_create_instance
from customer_security import customer_rate_limiter,remote_identity
from customer_team_api import CUSTOMER_TEAM_PATHS,dispatch_customer_team
from customer_team_repository import CustomerTeamRepository
from customer_verification_api import CUSTOMER_VERIFICATION_PATHS,dispatch_customer_verification
from instance_deletion_api import begin_deletion,deletion_status

CUSTOMER_PUBLIC_FILES={
    "/customer-login.html":legacy.WEB_DIR/"customer-login.html","/customer-register.html":legacy.WEB_DIR/"customer-register.html","/customer-forgot-password.html":legacy.WEB_DIR/"customer-forgot-password.html","/customer-reset-password.html":legacy.WEB_DIR/"customer-reset-password.html","/customer-verify-email.html":legacy.WEB_DIR/"customer-verify-email.html","/customer-invitation.html":legacy.WEB_DIR/"customer-invitation.html","/customer-auth.css":legacy.WEB_DIR/"customer-auth.css","/customer-auth.js":legacy.WEB_DIR/"customer-auth.js","/customer-onboarding.js":legacy.WEB_DIR/"customer-onboarding.js",
}
CUSTOMER_AUTHENTICATED_FILES={"/customer-members.html":legacy.WEB_DIR/"customer-members.html","/customer-members.js":legacy.WEB_DIR/"customer-members.js","/customer-team.css":legacy.WEB_DIR/"customer-team.css","/customer-deletion-v2.js":legacy.WEB_DIR/"customer-deletion-v2.js"}
legacy.STATIC_FILES.update(CUSTOMER_PUBLIC_FILES); legacy.STATIC_FILES.update(CUSTOMER_AUTHENTICATED_FILES)
_original_get=legacy.DashboardHandler.do_GET; _original_post=legacy.DashboardHandler.do_POST
_original_can_access_instance=legacy.can_access_instance; _original_instance_permission_profile=legacy.instance_permission_profile
_original_create_customer_instance=legacy.create_customer_instance; _original_authenticate=legacy.authenticate

def _backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
def _send(handler,result):
    if result is None:return False
    status,body=result; handler.send_json(status,body); return True
def _limit(handler,bucket,key,*,limit,window):
    decision=customer_rate_limiter.check(bucket,key,limit=limit,window_seconds=window)
    if decision.allowed:return True
    handler.send_response(429); handler.send_header("Content-Type","application/json; charset=utf-8"); handler.send_header("Retry-After",str(decision.retry_after)); body=b'{"error":"too many requests"}'; handler.send_header("Content-Length",str(len(body))); handler.end_headers(); handler.wfile.write(body); return False

def integrated_authenticate(headers):
    user=_original_authenticate(headers)
    if user is not None:return user
    try:return authenticate_customer(headers,_backend())
    except Exception:return None

def integrated_instance_permission_profile(user,instance_path,database_path=legacy.DATABASE_FILE):
    if user and user.get("role")=="customer":
        profile=customer_instance_profile(user,Path(instance_path).name,_backend())
        if profile:return profile
        metadata=legacy.instance_metadata(instance_path); owner=metadata.get("owner",{}) if isinstance(metadata,dict) else {}
        if isinstance(owner,dict) and owner.get("username")==user.get("username") and legacy.instance_customer_id(metadata)==user.get("scope_id"):return "manager"
        return None
    return _original_instance_permission_profile(user,instance_path,database_path)
def integrated_can_access_instance(user,instance_path,write=False):
    if user and user.get("role")=="customer":
        profile=integrated_instance_permission_profile(user,instance_path)
        if not profile:return False
        return profile in {"operator","manager"} if write else True
    return _original_can_access_instance(user,instance_path,write=write)
def integrated_create_customer_instance(user,payload,root=legacy.DSM_ROOT,database_path=legacy.DATABASE_FILE):
    if user and user.get("role")=="customer" and not may_create_instance(user,_backend()):raise PermissionError("customer account role cannot create instances")
    result=_original_create_customer_instance(user,payload,root=root,database_path=database_path)
    if user and user.get("role")=="customer" and result.get("instance_id"):CustomerTeamRepository(_backend()).set_instance_access(str(user["scope_id"]),str(user["username"]),str(result["instance_id"]),"manager")
    return result
legacy.authenticate=integrated_authenticate; legacy.instance_permission_profile=integrated_instance_permission_profile; legacy.can_access_instance=integrated_can_access_instance; legacy.create_customer_instance=integrated_create_customer_instance

def _instance_from_values(server,game,instance):
    return legacy.instance_identity_path(str(server or ""),str(game or ""),str(instance or ""))
def _authorized_instance(user,server,game,instance):
    path=_instance_from_values(server,game,instance)
    if not legacy.has_instance_permission(user,path,"instance.delete"):raise PermissionError("instance deletion is not allowed")
    return path

def _serve_instance_page(self):
    source=(legacy.WEB_DIR/"customer-instance.html").read_text(encoding="utf-8")
    marker="</body>"
    script='<script src="/customer-deletion-v2.js"></script>'
    body=(source.replace(marker,script+marker) if marker in source else source+script).encode("utf-8")
    self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

def integrated_get(self):
    parsed=urlparse(self.path); path=parsed.path
    if path in CUSTOMER_PUBLIC_FILES:self.send_file(CUSTOMER_PUBLIC_FILES[path]); return
    if path=="/customer-instance.html":_serve_instance_page(self); return
    if path=="/api/instance/delete/status":
        user=integrated_authenticate(self.headers)
        if not legacy.can_read(user):self.unauthorized(); return
        query=parse_qs(parsed.query)
        try:
            instance=_authorized_instance(user,query.get("server",[""])[0],query.get("game",[""])[0],query.get("instance",[""])[0])
            self.send_json(200,deletion_status(legacy.DSM_ROOT,instance.name))
        except PermissionError:self.forbidden()
        except (ValueError,OSError) as exc:self.send_json(400,{"error":str(exc)})
        return
    authenticated_get=path in CUSTOMER_AUTH_PATHS or path=="/api/customer/team" or path=="/api/customer/team/invitations" or path in AUTHENTICATED_PATHS
    user=None
    if authenticated_get:
        user=integrated_authenticate(self.headers)
        if not legacy.can_read(user):self.unauthorized(); return
    if path in CUSTOMER_AUTH_PATHS:_send(self,dispatch_customer_auth("GET",path,user=user,backend=_backend())); return
    if path=="/api/customer/team":_send(self,dispatch_customer_team("GET",path,payload=None,user=user,backend=_backend())); return
    if path=="/api/customer/team/invitations":_send(self,dispatch_customer_invitations("GET",path,payload=None,user=user,backend=_backend())); return
    if path in AUTHENTICATED_PATHS:
        if _send(self,dispatch_customer_account("GET",path,payload=None,user=user,backend=_backend())):return
    _original_get(self)

def integrated_post(self):
    path=urlparse(self.path).path; peer=remote_identity(self)
    if path=="/api/instance/delete":
        user=integrated_authenticate(self.headers)
        if user is None:self.unauthorized(); return
        if not legacy.can_write(user):self.forbidden(); return
        try:
            payload=self.read_json_body(); instance=_authorized_instance(user,payload.get("server"),payload.get("game"),payload.get("instance"))
            if payload.get("confirmation")!=instance.name:raise ValueError("instance identifier confirmation does not match")
            relative=instance.relative_to(legacy.INSTANCE_ROOT)
            server,game,_=relative.parts
            def stop():
                success,result=legacy.control_instance(user,instance,"stop")
                if not success:raise RuntimeError((result or {}).get("error","could not stop instance") if isinstance(result,dict) else "could not stop instance")
            def delete_record(instance_id):return legacy.dashboard_repository(legacy.DATABASE_FILE).delete_instance(instance_id)
            def audit(action,status,detail):legacy.audit(user,action,status,instance.name,detail,database_path=legacy.DATABASE_FILE)
            status,operation=begin_deletion(legacy.DSM_ROOT,instance,server=server,game=game,final_backup=payload.get("final_backup") is True,stop_instance=stop,delete_record=delete_record,audit=audit)
            self.send_json(status,operation)
        except PermissionError:self.forbidden()
        except (ValueError,OSError,RuntimeError) as exc:self.send_json(400,{"error":str(exc)})
        return
    if path in PUBLIC_PATHS|PUBLIC_INVITATION_PATHS|CUSTOMER_VERIFICATION_PATHS:
        limits={"/api/customer/register":(5,900),"/api/customer/password-recovery":(5,900),"/api/customer/password-reset":(10,900),"/api/customer/invitations/accept":(10,900),"/api/customer/email-verification":(10,900),"/api/customer/email-verification/resend":(5,900)}
        limit,window=limits[path]
        if not _limit(self,path,peer,limit=limit,window=window):return
        try:payload=self.read_json_body()
        except ValueError as exc:self.send_json(400,{"error":str(exc)}); return
        if path in PUBLIC_PATHS:_send(self,dispatch_customer_account("POST",path,payload=payload,user=None,backend=_backend())); return
        if path in PUBLIC_INVITATION_PATHS:_send(self,dispatch_customer_invitations("POST",path,payload=payload,user=None,backend=_backend())); return
        _send(self,dispatch_customer_verification("POST",path,payload=payload,backend=_backend())); return
    if path in (CUSTOMER_TEAM_PATHS-{"/api/customer/team"}) | (TEAM_INVITATION_PATHS-{"/api/customer/team/invitations"}):
        user=integrated_authenticate(self.headers)
        if user is None:self.unauthorized(); return
        if not legacy.can_write(user):self.forbidden(); return
        if not _limit(self,"customer-team-write",str(user.get("username","")),limit=60,window=60):return
        try:payload=self.read_json_body()
        except ValueError as exc:self.send_json(400,{"error":str(exc)}); return
        if path in CUSTOMER_TEAM_PATHS:_send(self,dispatch_customer_team("POST",path,payload=payload,user=user,backend=_backend())); return
        _send(self,dispatch_customer_invitations("POST",path,payload=payload,user=user,backend=_backend())); return
    if path in AUTHENTICATED_PATHS:
        user=integrated_authenticate(self.headers)
        if user is None:self.unauthorized(); return
        if not legacy.can_write(user):self.forbidden(); return
        try:payload=self.read_json_body()
        except ValueError as exc:self.send_json(400,{"error":str(exc)}); return
        if _send(self,dispatch_customer_account("POST",path,payload=payload,user=user,backend=_backend())):return
    _original_post(self)
legacy.DashboardHandler.do_GET=integrated_get; legacy.DashboardHandler.do_POST=integrated_post

def run():legacy.run()
if __name__=="__main__":run()
