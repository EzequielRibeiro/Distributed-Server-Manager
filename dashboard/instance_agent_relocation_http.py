#!/usr/bin/env python3
"""Scoped administrative API for safe cross-Agent instance relocation."""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse

from instance_agent_relocation_repository import InstanceAgentRelocationRepository, RelocationConflict

PATH = "/api/admin/instance/agent-relocation"


def install_instance_agent_relocation_http(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def enabled():
        # Fail closed until second-Agent restoration and fencing are certified.
        return os.environ.get("CAPIVARA_ENABLE_AGENT_RELOCATION") == "1"

    def service():
        backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
        return InstanceAgentRelocationRepository(backend, legacy.DSM_ROOT)

    def authorize(user, instance_id, *, mutate=False):
        role = str((user or {}).get("role") or "").lower()
        if role not in {"admin", "controller"}:
            raise PermissionError("instance administration required")
        repo = service()
        with repo.session() as session:
            row = session.execute(
                f"SELECT controller_id FROM instances WHERE id={repo.ph}", (instance_id,)
            ).fetchone()
        if row is None:
            raise LookupError("instance not found")
        if role == "controller" and str(user.get("scope_id") or "") != str(row["controller_id"]):
            raise PermissionError("instance belongs to another Controller")
        if mutate and role not in {"admin", "controller"}:
            raise PermissionError("write access denied")
        return repo

    def public_state(item):
        allowed = (
            "relocation_id", "instance_id", "source_agent_id", "target_agent_id", "status",
            "source_running", "source_ports", "target_ports", "last_error",
            "created_at", "updated_at", "completed_at",
        )
        return {key: item.get(key) for key in allowed}

    def failure(self, exc):
        if isinstance(exc, PermissionError):
            return self.send_json(403, {"error": "forbidden", "message": str(exc)})
        if isinstance(exc, (LookupError, KeyError)):
            return self.send_json(404, {"error": "not_found", "message": str(exc)})
        if isinstance(exc, RelocationConflict):
            return self.send_json(409, {"error": "operation_conflict", "message": str(exc)})
        if isinstance(exc, (ValueError, TypeError)):
            return self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        return self.send_json(500, {"error": "relocation_error", "message": "Falha ao consultar migração."})

    def user_for(self):
        actor = authenticate(self.headers)
        if actor is None:
            self.unauthorized()
        return actor

    def get(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_get(self)
        actor = user_for(self)
        if actor is None:
            return
        try:
            query = parse_qs(parsed.query)
            relocation_id = str((query.get("relocation_id") or [""])[0]).strip()
            repo = service()
            repo.initialize()
            if relocation_id:
                item = repo.get(relocation_id)
                authorize(actor, item["instance_id"])
                return self.send_json(200, {"relocation": public_state(item), "enabled": enabled()})
            instance_id = str((query.get("instance_id") or [""])[0]).strip()
            repo = authorize(actor, instance_id)
            target_id = str((query.get("target_agent_id") or [""])[0]).strip()
            if target_id:
                return self.send_json(200, {"preflight": repo.preflight(instance_id, target_id),
                                            "enabled": enabled()})
            with repo.session() as session:
                current = session.execute(
                    f"SELECT agent_id,controller_id FROM instances WHERE id={repo.ph}", (instance_id,)
                ).fetchone()
                agents = session.execute(
                    f"SELECT id,name,node_id,status FROM agents WHERE controller_id={repo.ph} "
                    f"AND id<>{repo.ph} ORDER BY name,id",
                    (current["controller_id"], current["agent_id"]),
                ).fetchall()
            return self.send_json(200, {
                "agents": [dict(row) for row in agents],
                "relocations": [public_state(item) for item in repo.list_for_instance(instance_id)],
                "enabled": enabled(),
            })
        except Exception as exc:
            return failure(self, exc)

    def post(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_post(self)
        actor = user_for(self)
        if actor is None:
            return
        try:
            payload = self.read_json_body()
            if not isinstance(payload, dict) or payload.get("action") != "start":
                raise ValueError("action=start required")
            instance_id = str(payload.get("instance_id") or "").strip()
            target_id = str(payload.get("target_agent_id") or "").strip()
            repo = authorize(actor, instance_id, mutate=True)
            if not enabled():
                return self.send_json(423, {
                    "error": "relocation_not_certified",
                    "message": "Migração indisponível até concluir homologação entre dois Agents."
                })
            item = repo.enqueue(
                instance_id, target_id,
                requested_by=str(actor.get("username") or actor.get("id") or "admin"),
                confirmation=str(payload.get("confirmation") or ""),
            )
            try:
                legacy.audit(actor, "instance.agent-relocation", "started", instance_id,
                             f"relocation={item['relocation_id']};target={target_id}")
            except Exception:
                pass
            return self.send_json(202, {"relocation": public_state(item)})
        except Exception as exc:
            return failure(self, exc)

    legacy.DashboardHandler.do_GET = get
    legacy.DashboardHandler.do_POST = post


__all__ = ["PATH", "install_instance_agent_relocation_http"]
