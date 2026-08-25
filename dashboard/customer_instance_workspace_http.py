#!/usr/bin/env python3
"""HTTP integration for Customer Instance Workspace v2."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService

PREFIX="/api/customer/instance/workspace"
ROUTES={
    PREFIX,
    PREFIX+"/telemetry",
    PREFIX+"/console",
    PREFIX+"/startup",
    PREFIX+"/backup-policy",
    PREFIX+"/upgrade-options",
    PREFIX+"/upgrade",
    PREFIX+"/runtime-options",
    PREFIX+"/permissions",
}


def install_customer_instance_workspace(legacy, authenticate) -> None:
    previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST;previous_patch=getattr(legacy.DashboardHandler,"do_PATCH",None)
    legacy.STATIC_FILES.update({
        "/customer-instance.html":legacy.WEB_DIR/"customer-instance.html",
        "/customer-instance-v2.js":legacy.WEB_DIR/"customer-instance-v2.js",
        "/customer-instance-v2.css":legacy.WEB_DIR/"customer-instance-v2.css",
    })
    def service():return CustomerInstanceWorkspaceService(legacy.dashboard_repository(legacy.DATABASE_FILE).backend,legacy.DSM_ROOT)
    def user_for(self):
        user=session_user_from_headers(self.headers)
        if user is not None:return user
        try:return authenticate(self.headers)
        except Exception:return None
    def require_user(self):
        user=user_for(self)
        if user is None:self.unauthorized();return None
        if str(user.get("role") or "").lower() not in {"customer","admin","controller"}:self.forbidden();return None
        return user
    def one(parsed,name,default=None):return (parse_qs(parsed.query,keep_blank_values=True).get(name) or [default])[0]
    def instance(parsed,body=None):return str((body or {}).get("instance_id") or one(parsed,"instance_id","") or "").strip()
    def send_error(self,exc):
        if isinstance(exc,PermissionError):self.send_json(403,{"error":"forbidden","message":str(exc)});return
        if isinstance(exc,KeyError):self.send_json(404,{"error":"not_found","message":"Instância não encontrada."});return
        if isinstance(exc,(ValueError,LookupError)):self.send_json(400,{"error":"invalid_request","message":str(exc)});return
        self.send_json(500,{"error":"workspace_failed","message":"Não foi possível concluir a operação da instância."})
    def get(self):
        parsed=urlparse(self.path);path=parsed.path
        if path not in ROUTES:return previous_get(self)
        user=require_user(self)
        if user is None:return
        iid=instance(parsed)
        try:
            api=service()
            if path==PREFIX:data=api.overview(user,iid)
            elif path==PREFIX+"/telemetry":data={"samples":api.telemetry(user,iid,int(one(parsed,"limit",240) or 240))}
            elif path==PREFIX+"/console":data={"lines":api.console_output(user,iid,int(one(parsed,"limit",300) or 300))}
            elif path==PREFIX+"/startup":data=api.startup(user,iid)
            elif path==PREFIX+"/backup-policy":data=api.backup_policy(user,iid)
            elif path==PREFIX+"/upgrade-options":data=api.upgrade_options(user,iid)
            elif path==PREFIX+"/runtime-options":data={"runtimes":api.runtime_options(user,iid)}
            elif path==PREFIX+"/permissions":data={"permissions":sorted(api.permissions(user,iid))}
            else:data={"changes":api.repo.list_contract_changes(iid)}
            self.send_json(200,data)
        except Exception as exc:send_error(self,exc)
    def post(self):
        parsed=urlparse(self.path);path=parsed.path
        if path not in {PREFIX+"/console",PREFIX+"/upgrade"}:return previous_post(self)
        user=require_user(self)
        if user is None:return
        try:
            body=self.read_json_body();iid=instance(parsed,body);api=service()
            if path==PREFIX+"/console":data=api.send_console(user,iid,body.get("command"));code=202
            else:data=api.request_upgrade(user,iid,body.get("profile_id"));code=202
            self.send_json(code,data)
        except Exception as exc:send_error(self,exc)
    def patch(self):
        parsed=urlparse(self.path);path=parsed.path
        if path not in {PREFIX+"/startup",PREFIX+"/backup-policy"}:
            if previous_patch is not None:return previous_patch(self)
            self.send_json(404,{"error":"not_found"});return
        user=require_user(self)
        if user is None:return
        try:
            body=self.read_json_body();iid=instance(parsed,body);api=service()
            data=api.save_startup(user,iid,body.get("values")) if path.endswith("startup") else api.save_backup_policy(user,iid,body)
            self.send_json(200,data)
        except Exception as exc:send_error(self,exc)
    legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post;legacy.DashboardHandler.do_PATCH=patch


__all__=["PREFIX","ROUTES","install_customer_instance_workspace"]
