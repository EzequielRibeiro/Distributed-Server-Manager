#!/usr/bin/env python3
"""Customer/lifecycle HTTP integration wrapper for Capivara DSM."""
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
from controller_session import create_session,cookie_header,session_user_from_headers
from deleted_instance_backup import complete_deleted_instance_backup_download,pending_deleted_backups,resolve_deleted_instance_backup
from instance_deletion_api import begin_deletion,deletion_status
from instance_lifecycle_http import dispatch_instance_lifecycle_get,dispatch_instance_lifecycle_post,dispatch_instance_reinstall_post
from instance_reinstall_service import reinstall_instance,reinstall_busy

CUSTOMER_PUBLIC_FILES={"/customer-login.html":legacy.WEB_DIR/"customer-login.html","/customer-register.html":legacy.WEB_DIR/"customer-register.html","/customer-forgot-password.html":legacy.WEB_DIR/"customer-forgot-password.html","/customer-reset-password.html":legacy.WEB_DIR/"customer-reset-password.html","/customer-verify-email.html":legacy.WEB_DIR/"customer-verify-email.html","/customer-invitation.html":legacy.WEB_DIR/"customer-invitation.html","/customer-auth.css":legacy.WEB_DIR/"customer-auth.css","/customer-auth.js":legacy.WEB_DIR/"customer-auth.js","/customer-onboarding.js":legacy.WEB_DIR/"customer-onboarding.js"}
CUSTOMER_AUTHENTICATED_FILES={"/customer-members.html":legacy.WEB_DIR/"customer-members.html","/customer-members.js":legacy.WEB_DIR/"customer-members.js","/customer-team.css":legacy.WEB_DIR/"customer-team.css","/customer-deletion-v2.js":legacy.WEB_DIR/"customer-deletion-v2.js","/customer-overview-v2.js":legacy.WEB_DIR/"customer-overview-v2.js","/instance-lifecycle-v2.js":legacy.WEB_DIR/"instance-lifecycle-v2.js"}
CUSTOMER_PROTECTED_PAGES={"/customer.html","/customer-instance.html","/customer-members.html"};CONTROLLER_PROTECTED_PAGES={"/","/index.html","/console.html","/settings.html","/users.html","/agents.html","/contract-demo.html"}
legacy.STATIC_FILES.update(CUSTOMER_PUBLIC_FILES);legacy.STATIC_FILES.update(CUSTOMER_AUTHENTICATED_FILES)
_original_get=legacy.DashboardHandler.do_GET;_original_post=legacy.DashboardHandler.do_POST;_original_can_access_instance=legacy.can_access_instance;_original_instance_permission_profile=legacy.instance_permission_profile;_original_create_customer_instance=legacy.create_customer_instance;_original_authenticate=legacy.authenticate

def _backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
def _send(handler,result):
    if result is None:return False
    status,body=result;handler.send_json(status,body);return True
def _limit(handler,bucket,key,*,limit,window):
    decision=customer_rate_limiter.check(bucket,key,limit=limit,window_seconds=window)
    if decision.allowed:return True
    handler.send_response(429);handler.send_header("Content-Type","application/json; charset=utf-8");handler.send_header("Retry-After",str(decision.retry_after));body=b'{"error":"too many requests"}';handler.send_header("Content-Length",str(len(body)));handler.end_headers();handler.wfile.write(body);return False
def integrated_authenticate(headers):
    user=_original_authenticate(headers)
    if user is not None:return user
    try:return authenticate_customer(headers,_backend())
    except Exception:return None
def _require_area_role(handler,user,allowed_roles):
    if user is None:handler.unauthorized();return False
    if user.get("role") not in allowed_roles:handler.forbidden();return False
    return True
def integrated_instance_permission_profile(user,instance_path,database_path=legacy.DATABASE_FILE):
    if user and user.get("role")=="customer":
        profile=customer_instance_profile(user,Path(instance_path).name,_backend())
        if profile:return profile
        metadata=legacy.instance_metadata(instance_path);owner=metadata.get("owner",{}) if isinstance(metadata,dict) else {}
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
legacy.authenticate=integrated_authenticate;legacy.instance_permission_profile=integrated_instance_permission_profile;legacy.can_access_instance=integrated_can_access_instance;legacy.create_customer_instance=integrated_create_customer_instance

def _instance_from_values(server,game,instance):return legacy.instance_identity_path(str(server or ""),str(game or ""),str(instance or ""))
def _html_with_scripts(source:Path,scripts:list[str]):
    text=source.read_text(encoding="utf-8");tags="".join(f'<script src="{item}"></script>' for item in scripts);return (text.replace("</body>",tags+"</body>") if "</body>" in text else text+tags).encode("utf-8")
def _send_html(self,body):self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
def _serve_instance_page(self):_send_html(self,_html_with_scripts(legacy.WEB_DIR/"customer-instance.html",["/customer-deletion-v2.js","/customer-overview-v2.js"]))
def _serve_customer_page(self):_send_html(self,_html_with_scripts(legacy.WEB_DIR/"customer.html",["/customer-deleted-backups.js"]))
def _serve_controller_page(self):_send_html(self,_html_with_scripts(legacy.WEB_DIR/"index.html",["/instance-lifecycle-v2.js"]))

def integrated_get(self):
    parsed=urlparse(self.path);path=parsed.path
    if path in CUSTOMER_PUBLIC_FILES:self.send_file(CUSTOMER_PUBLIC_FILES[path]);return
    if path=="/customer-deleted-backups.js":
        user=integrated_authenticate(self.headers)
        if not _require_area_role(self,user,{"customer"}):return
        self.send_file(legacy.WEB_DIR/"customer-deleted-backups.js");return
    if path in CUSTOMER_AUTHENTICATED_FILES:
        user=integrated_authenticate(self.headers)
        if not _require_area_role(self,user,{"customer"}):return
        self.send_file(CUSTOMER_AUTHENTICATED_FILES[path]);return
    if path in CUSTOMER_PROTECTED_PAGES:
        user=session_user_from_headers(self.headers)
        if user is None:
            self.send_response(302)
            self.send_header("Location","/customer-login.html")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length","0")
            self.end_headers()
            return
        if not _require_area_role(self,user,{"customer"}):return
        if path=="/customer-instance.html":_serve_instance_page(self)
        elif path=="/customer.html":_serve_customer_page(self)
        else:self.send_file(legacy.STATIC_FILES[path])
        return
    if path in CONTROLLER_PROTECTED_PAGES:
        user=session_user_from_headers(self.headers)
        if user is None:
            self.send_response(302)
            self.send_header("Location","/login.html")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length","0")
            self.end_headers()
            return
        if not _require_area_role(
            self,user,{"admin","controller","operator"}
        ):
            return
        if path in {"/","/index.html"}:
            _serve_controller_page(self)
        else:
            self.send_file(legacy.STATIC_FILES[path])
        return
    if path=="/api/instance/delete/backups":
        user=integrated_authenticate(self.headers)
        if user is None:self.unauthorized();return
        try:self.send_json(200,{"backups":pending_deleted_backups(legacy.DSM_ROOT,user)})
        except PermissionError:self.forbidden()
        except OSError as exc:self.send_json(400,{"error":str(exc)})
        return
    if path=="/api/instance/delete/backup":
        user=integrated_authenticate(self.headers)
        if user is None:self.unauthorized();return
        try:
            query=parse_qs(parsed.query,keep_blank_values=True);instance_id=str((query.get("instance") or [""])[0]).strip();backup,_=resolve_deleted_instance_backup(legacy.DSM_ROOT,instance_id,user);size=backup.stat().st_size
            self.send_response(200);self.send_header("Content-Type","application/gzip");self.send_header("Content-Disposition",f'attachment; filename="{backup.name}"');self.send_header("Content-Length",str(size));self.send_header("Cache-Control","no-store");self.end_headers()
            sent=0
            with backup.open("rb") as source:
                while True:
                    chunk=source.read(1024*1024)
                    if not chunk:break
                    self.wfile.write(chunk);sent+=len(chunk)
            self.wfile.flush()
            if sent==size:complete_deleted_instance_backup_download(legacy.DSM_ROOT,instance_id,user)
            return
        except (BrokenPipeError,ConnectionResetError):return
        except PermissionError:self.forbidden()
        except FileNotFoundError as exc:self.send_json(404,{"error":str(exc)})
        except (ValueError,OSError) as exc:self.send_json(400,{"error":str(exc)})
        return
    if path=="/api/instance/delete/status":
        user=integrated_authenticate(self.headers)
        if not legacy.can_read(user):self.unauthorized();return
        try:
            result=dispatch_instance_lifecycle_get(path,parsed.query,user=user,root=legacy.DSM_ROOT,resolve_instance=_instance_from_values,can_access=integrated_can_access_instance,deletion_status=deletion_status)
            if _send(self,result):return
        except PermissionError:self.forbidden()
        except (ValueError,OSError) as exc:self.send_json(400,{"error":str(exc)})
        return
    authenticated_get=path in CUSTOMER_AUTH_PATHS or path=="/api/customer/team" or path=="/api/customer/team/invitations" or path in AUTHENTICATED_PATHS;user=None
    if authenticated_get:
        user=integrated_authenticate(self.headers)
        if not _require_area_role(self,user,{"customer"}):return
    if path in CUSTOMER_AUTH_PATHS:_send(self,dispatch_customer_auth("GET",path,user=user,backend=_backend()));return
    if path=="/api/customer/team":_send(self,dispatch_customer_team("GET",path,payload=None,user=user,backend=_backend()));return
    if path=="/api/customer/team/invitations":_send(self,dispatch_customer_invitations("GET",path,payload=None,user=user,backend=_backend()));return
    if path in AUTHENTICATED_PATHS:
        if _send(self,dispatch_customer_account("GET",path,payload=None,user=user,backend=_backend())):return
    _original_get(self)

def integrated_post(self):
    path=urlparse(self.path).path;peer=remote_identity(self)
    if path=="/api/instance/reinstall/v2":
        user=integrated_authenticate(self.headers)
        if user is None:self.unauthorized();return
        if user.get("role") not in {"admin","controller"}:self.forbidden();return
        try:
            payload=self.read_json_body();instance=Path(_instance_from_values(payload.get("server"),payload.get("game"),payload.get("instance")));server,game,_=instance.relative_to(legacy.INSTANCE_ROOT).parts
            def runner(preserve):return legacy.reinstall_instance_from_game_data(user,server,game,instance.name,preserve_config=preserve)
            result=dispatch_instance_reinstall_post(path,payload,user=user,resolve_instance=_instance_from_values,can_access=integrated_can_access_instance,reinstall_busy=reinstall_busy,reinstall_instance=reinstall_instance,runner=runner,deletion_status=deletion_status,root=legacy.DSM_ROOT)
            if _send(self,result):return
        except RuntimeError as exc:self.send_json(409,{"error":str(exc)})
        except PermissionError:self.forbidden()
        except (ValueError,OSError) as exc:self.send_json(400,{"error":str(exc)})
        return
    if path=="/api/auth/login":
        user=integrated_authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        if user.get("role") not in {"admin","controller","operator","customer"}:
            self.forbidden()
            return
        token=create_session(user)
        body=b'{"authenticated":true}'
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Set-Cookie",cookie_header(token))
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return
    if path=="/api/instance/delete":
        user=integrated_authenticate(self.headers)
        if user is None:self.unauthorized();return
        if not legacy.can_write(user):self.forbidden();return
        try:
            payload=self.read_json_body();instance=_instance_from_values(payload.get("server"),payload.get("game"),payload.get("instance"))
            def stop():
                success,result=legacy.control_instance(user,instance,"stop")
                if not success:raise RuntimeError((result or {}).get("error","could not stop instance") if isinstance(result,dict) else "could not stop instance")
            def delete_record(instance_id):return legacy.dashboard_repository(legacy.DATABASE_FILE).delete_instance(instance_id)
            def audit(action,status,detail):
                audit_instance_id=getattr(instance,"name",None) or str(instance).rstrip("/").rsplit("/",1)[-1];legacy.audit(user,action,status,audit_instance_id,detail,database_path=legacy.DATABASE_FILE)
            result=dispatch_instance_lifecycle_post(path,payload,user=user,root=legacy.DSM_ROOT,resolve_instance=_instance_from_values,has_permission=legacy.has_instance_permission,begin_deletion=begin_deletion,stop_instance=stop,delete_record=delete_record,audit=audit,reinstall_busy=reinstall_busy)
            if _send(self,result):return
        except PermissionError:self.forbidden()
        except (ValueError,OSError,RuntimeError) as exc:self.send_json(400,{"error":str(exc)})
        return
    if path in PUBLIC_PATHS|PUBLIC_INVITATION_PATHS|CUSTOMER_VERIFICATION_PATHS:
        limits={"/api/customer/register":(5,900),"/api/customer/password-recovery":(5,900),"/api/customer/password-reset":(10,900),"/api/customer/invitations/accept":(10,900),"/api/customer/email-verification":(10,900),"/api/customer/email-verification/resend":(5,900)};limit,window=limits[path]
        if not _limit(self,path,peer,limit=limit,window=window):return
        try:payload=self.read_json_body()
        except ValueError as exc:self.send_json(400,{"error":str(exc)});return
        if path in PUBLIC_PATHS:_send(self,dispatch_customer_account("POST",path,payload=payload,user=None,backend=_backend()));return
        if path in PUBLIC_INVITATION_PATHS:_send(self,dispatch_customer_invitations("POST",path,payload=payload,user=None,backend=_backend()));return
        _send(self,dispatch_customer_verification("POST",path,payload=payload,backend=_backend()));return
    if path in (CUSTOMER_TEAM_PATHS-{"/api/customer/team"})|(TEAM_INVITATION_PATHS-{"/api/customer/team/invitations"}):
        user=integrated_authenticate(self.headers)
        if not _require_area_role(self,user,{"customer"}):return
        if not legacy.can_write(user):self.forbidden();return
        if not _limit(self,"customer-team-write",str(user.get("username","")),limit=60,window=60):return
        try:payload=self.read_json_body()
        except ValueError as exc:self.send_json(400,{"error":str(exc)});return
        if path in CUSTOMER_TEAM_PATHS:_send(self,dispatch_customer_team("POST",path,payload=payload,user=user,backend=_backend()));return
        _send(self,dispatch_customer_invitations("POST",path,payload=payload,user=user,backend=_backend()));return
    if path in AUTHENTICATED_PATHS:
        user=integrated_authenticate(self.headers)
        if not _require_area_role(self,user,{"customer"}):return
        if not legacy.can_write(user):self.forbidden();return
        try:payload=self.read_json_body()
        except ValueError as exc:self.send_json(400,{"error":str(exc)});return
        if _send(self,dispatch_customer_account("POST",path,payload=payload,user=user,backend=_backend())):return
    _original_post(self)
legacy.DashboardHandler.do_GET=integrated_get;legacy.DashboardHandler.do_POST=integrated_post

def run():legacy.run()
if __name__=="__main__":run()
