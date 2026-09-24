#!/usr/bin/env python3
"""Customer DayZ map discovery/change and wipe surface."""
from __future__ import annotations
from datetime import datetime,timezone
from urllib.parse import parse_qs,urlparse
from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from customer_content_workspace import CustomerContentWorkspaceService
from dayz_management_repository import DayZManagementRepository,DayZOperationConflict
from json_serialization import to_json_compatible

PATH="/api/customer/instance/dayz"
COMMUNITY_MAP=PATH+"/community-map"
DISCOVERY_SCHEMA_VERSION=2

def _discovery_payload(op):
    if not isinstance(op,dict) or op.get("action")!="discover_missions" or op.get("status")!="completed":return None
    payload=(op.get("result") or {}).get("result")
    if not isinstance(payload,dict) or int(payload.get("schema_version") or 0)<DISCOVERY_SCHEMA_VERSION:return None
    missions=payload.get("missions")
    if not isinstance(missions,list):return None
    required={"id","official","community","active","installed","available","can_activate","state","source"}
    if any(not isinstance(item,dict) or not required.issubset(item) for item in missions):return None
    return payload

def install_customer_dayz_http(legacy,authenticate):
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
    def iid(parsed,body=None):return str((body or {}).get("instance_id") or (parse_qs(parsed.query).get("instance_id") or [""])[0]).strip()
    def service(user,instance_id,permission="instance.view"):
        workspace=CustomerInstanceWorkspaceService(backend(),legacy.DSM_ROOT);context=workspace.require(user,instance_id,permission)
        if str(context.get("game_id") or "").lower()!="dayz":raise ValueError("DayZ management is available only for DayZ instances")
        return workspace,context,DayZManagementRepository(backend())
    def view(user,instance_id):
        workspace,context,repo=service(user,instance_id);repo.initialize();ops=repo.list_for_instance(instance_id,25)
        discovery=next(((op,_discovery_payload(op)) for op in ops if _discovery_payload(op) is not None),None)
        active_discovery=next((op for op in ops if op.get("action")=="discover_missions" and op.get("status") in {"queued","delivered"}),None)
        latest_change=next((op for op in ops if op.get("action")=="change_mission" and op.get("status")=="completed"),None)
        discovery_created=(discovery[0].get("created_at") if discovery else None)
        change_completed=(latest_change.get("completed_at") if latest_change else None)
        stale_after_change=bool(latest_change and (discovery is None or (change_completed and discovery_created and change_completed>discovery_created)))
        if (discovery is None or stale_after_change) and active_discovery is None:
            actor=str((user or {}).get("username") or (user or {}).get("id") or "customer")
            repo.enqueue(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,action="discover_missions",requested_by=actor)
            ops=repo.list_for_instance(instance_id,25)
        discovery=next(((op,_discovery_payload(op)) for op in ops if _discovery_payload(op) is not None),None)
        maps=discovery[1] if discovery else {}
        return {"instance_id":instance_id,"editable":"instance.restart" in workspace.permissions(user,instance_id) and "settings.write" in workspace.permissions(user,instance_id),"maps":maps,"operations":[{k:op.get(k) for k in ("operation_id","action","status","scheduled_at","last_error","created_at","delivered_at","completed_at","canceled_at","payload","result")} for op in ops[:15]]}
    def error(self,exc):
        if isinstance(exc,PermissionError):return send(self,403,{"error":"forbidden","message":str(exc)})
        if isinstance(exc,KeyError):return send(self,404,{"error":"not_found","message":"Instância não encontrada."})
        if isinstance(exc,(DayZOperationConflict,RuntimeError)):return send(self,409,{"error":"operation_conflict","message":str(exc)})
        if isinstance(exc,(ValueError,LookupError)):return send(self,400,{"error":"invalid_request","message":str(exc)})
        return send(self,500,{"error":"dayz_management_failed","message":"Não foi possível concluir a operação DayZ."})
    def get(self):
        parsed=urlparse(self.path)
        if parsed.path!=PATH:return previous_get(self)
        user=require_user(self)
        if user is None:return
        try:return send(self,200,view(user,iid(parsed)))
        except Exception as exc:return error(self,exc)
    def post(self):
        parsed=urlparse(self.path)
        if parsed.path not in {PATH,COMMUNITY_MAP}:return previous_post(self)
        user=require_user(self)
        if user is None:return
        try:
            body=self.read_json_body();instance_id=iid(parsed,body)
            if parsed.path==COMMUNITY_MAP:
                result=CustomerContentWorkspaceService(backend(),legacy.DSM_ROOT).install_dayz_community_map(user,instance_id,body)
                return send(self,202,{"community_map":result,"view":view(user,instance_id)})
            workspace,context,repo=service(user,instance_id,"instance.restart");workspace.require(user,instance_id,"settings.write");repo.initialize()
            action=str(body.get("action") or "").strip().lower();actor=str(user.get("username") or user.get("id") or "customer")
            if action=="refresh_maps":queued=repo.enqueue(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,action="discover_missions",requested_by=actor)
            elif action=="change_mission":
                mission=str(body.get("mission") or "").strip()
                if not mission:raise ValueError("mission is required")
                content_mode=str(body.get("content_mode") or "disable").strip().lower()
                if content_mode not in {"disable","keep"}:raise ValueError("invalid DayZ map content mode")
                persistence_mode=str(body.get("persistence_mode") or "fresh").strip().lower()
                if persistence_mode not in {"fresh","keep"}:raise ValueError("invalid DayZ map persistence mode")
                queued=repo.enqueue(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,action="change_mission",payload={"mission":mission,"content_mode":content_mode,"persistence_mode":persistence_mode},requested_by=actor)
            elif action=="wipe":
                scheduled_at=body.get("scheduled_at")
                if scheduled_at:
                    parsed_due=datetime.fromisoformat(str(scheduled_at).replace("Z","+00:00"))
                    if parsed_due.tzinfo is None:raise ValueError("scheduled_at must include timezone")
                    if parsed_due.astimezone(timezone.utc)<=datetime.now(timezone.utc):raise ValueError("scheduled_at must be in the future")
                queued=repo.enqueue(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,action="wipe",payload={"scope":str(body.get("scope") or "persistence"),"backup":body.get("backup",True) is not False},scheduled_at=scheduled_at,requested_by=actor)
            elif action=="cancel":
                operation_id=str(body.get("operation_id") or "").strip()
                current=repo.snapshot(operation_id)
                if str(current.get("instance_id") or "")!=instance_id:raise PermissionError("operation belongs to another instance")
                queued=repo.cancel(operation_id)
            else:raise ValueError("unsupported DayZ customer action")
            return send(self,202,{"operation":queued,"view":view(user,instance_id)})
        except Exception as exc:return error(self,exc)
    legacy.DashboardHandler.do_GET=get;legacy.DashboardHandler.do_POST=post

__all__=["COMMUNITY_MAP","PATH","install_customer_dayz_http"]
