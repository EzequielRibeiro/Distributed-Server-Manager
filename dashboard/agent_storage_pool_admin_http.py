#!/usr/bin/env python3
"""HTTP composition for managed Agent Storage Pool CRUD."""
from __future__ import annotations
from urllib.parse import parse_qs, urlparse

from agent_admin_repository import AgentAdminRepository
from agent_storage_pool_admin import AgentStoragePoolAdmin
from universal_event_repository import UniversalEventRepository

PATH = "/api/admin/agent/storage-pools"


def _role(user): return str((user or {}).get("role") or "").strip().lower()

def _authorize(user, detail):
    role=_role(user)
    if role=="admin": return
    if role=="controller" and str(user.get("scope_id") or "")==str(detail.get("controller_id") or ""): return
    raise PermissionError("Storage Pool administration access denied")

def _event(backend, *, event_type, agent_id, actor, data):
    UniversalEventRepository(backend).publish({"event_type":event_type,"source":"dashboard.agent-storage-pools","source_id":agent_id,
        "severity":"info","agent_id":agent_id,"actor_type":"user","actor_id":actor,"data":dict(data or {})})

def install_agent_storage_pool_administration(legacy, authenticate):
    previous_get=legacy.DashboardHandler.do_GET; previous_post=legacy.DashboardHandler.do_POST; previous_delete=getattr(legacy.DashboardHandler,"do_DELETE",None)
    def backend(): return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
    def user(self):
        value=authenticate(self.headers)
        if value is None: self.unauthorized()
        return value
    def do_get(self):
        parsed=urlparse(self.path)
        if parsed.path!=PATH: return previous_get(self)
        actor=user(self)
        if actor is None:return
        try:
            values=parse_qs(parsed.query or ""); agent_id=str((values.get("agent_id") or [""])[0]).strip(); b=backend()
            detail=AgentAdminRepository(b).detail(agent_id); _authorize(actor,detail)
            service=AgentStoragePoolAdmin(b); service.initialize(); self.send_json(200,{"storage_pools":service.detail(agent_id)})
        except PermissionError as exc:self.send_json(403,{"error":"forbidden","message":str(exc)})
        except LookupError as exc:self.send_json(404,{"error":"not_found","message":str(exc)})
        except (ValueError,TypeError) as exc:self.send_json(400,{"error":"invalid_request","message":str(exc)})
        except Exception:self.send_json(500,{"error":"storage_pool_admin_failed","message":"Falha ao consultar Storage Pools."})
    def do_post(self):
        parsed=urlparse(self.path)
        if parsed.path!=PATH:return previous_post(self)
        actor=user(self)
        if actor is None:return
        try: payload=self.read_json_body()
        except ValueError:self.send_json(400,{"error":"invalid_request","message":"Requisição inválida."});return
        try:
            b=backend(); agent_id=str((payload or {}).get("agent_id") or "").strip(); detail=AgentAdminRepository(b).detail(agent_id); _authorize(actor,detail)
            username=str(actor.get("username") or "system"); action=str((payload or {}).get("action") or "upsert").strip().lower(); service=AgentStoragePoolAdmin(b);service.initialize()
            if action=="upsert":
                result,pool_id,created=service.upsert(agent_id,dict((payload or {}).get("pool") or {}),actor=username)
                _event(b,event_type="AGENT_STORAGE_POOL_CREATED" if created else "AGENT_STORAGE_POOL_UPDATED",agent_id=agent_id,actor=username,data={"storage_pool_id":pool_id})
            elif action in {"enable","disable"}:
                pool_id=str((payload or {}).get("storage_pool_id") or ""); enabled=action=="enable"; result=service.set_enabled(agent_id,pool_id,enabled,actor=username)
                _event(b,event_type="AGENT_STORAGE_POOL_ENABLED" if enabled else "AGENT_STORAGE_POOL_DISABLED",agent_id=agent_id,actor=username,data={"storage_pool_id":pool_id})
            elif action=="set-default":
                pool_id=str((payload or {}).get("storage_pool_id") or ""); result=service.set_default(agent_id,pool_id,actor=username)
                _event(b,event_type="AGENT_STORAGE_POOL_DEFAULT_CHANGED",agent_id=agent_id,actor=username,data={"storage_pool_id":pool_id})
            else: raise ValueError("unsupported Storage Pool action")
            self.send_json(202,{"storage_pools":result})
        except PermissionError as exc:self.send_json(403,{"error":"forbidden","message":str(exc)})
        except LookupError as exc:self.send_json(404,{"error":"not_found","message":str(exc)})
        except (ValueError,TypeError) as exc:self.send_json(400,{"error":"invalid_request","message":str(exc)})
        except Exception:self.send_json(500,{"error":"storage_pool_admin_failed","message":"Falha ao alterar Storage Pool."})
    def do_delete(self):
        parsed=urlparse(self.path)
        if parsed.path!=PATH:
            if previous_delete:return previous_delete(self)
            self.send_error(404);return
        actor=user(self)
        if actor is None:return
        try:
            values=parse_qs(parsed.query or ""); agent_id=str((values.get("agent_id") or [""])[0]).strip(); pool_id=str((values.get("storage_pool_id") or [""])[0]).strip();b=backend()
            detail=AgentAdminRepository(b).detail(agent_id);_authorize(actor,detail);username=str(actor.get("username") or "system")
            service=AgentStoragePoolAdmin(b);service.initialize();result=service.remove(agent_id,pool_id,actor=username)
            _event(b,event_type="AGENT_STORAGE_POOL_REMOVED",agent_id=agent_id,actor=username,data={"storage_pool_id":pool_id})
            self.send_json(202,{"storage_pools":result})
        except PermissionError as exc:self.send_json(403,{"error":"forbidden","message":str(exc)})
        except LookupError as exc:self.send_json(404,{"error":"not_found","message":str(exc)})
        except (ValueError,TypeError) as exc:self.send_json(400,{"error":"invalid_request","message":str(exc)})
        except Exception:self.send_json(500,{"error":"storage_pool_admin_failed","message":"Falha ao remover Storage Pool."})
    legacy.DashboardHandler.do_GET=do_get;legacy.DashboardHandler.do_POST=do_post;legacy.DashboardHandler.do_DELETE=do_delete

__all__=["PATH","install_agent_storage_pool_administration"]
