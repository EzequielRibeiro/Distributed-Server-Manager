#!/usr/bin/env python3
"""Administrative HTTP API for Agent player-facing public network identity."""
from __future__ import annotations
from urllib.parse import parse_qs, urlparse

from agent_public_network import AgentPublicNetworkRepository

PATH = "/api/admin/agent/public-network"


def install_agent_public_network(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    legacy.STATIC_FILES["/agent-public-network.js"] = legacy.WEB_DIR / "agent-public-network.js"

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def require_manager(self):
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return None
        if str(user.get("role") or "").lower() not in {"admin", "controller"}:
            self.forbidden()
            return None
        return user

    def get(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_get(self)
        user = require_manager(self)
        if user is None:
            return
        agent_id = str((parse_qs(parsed.query).get("agent_id") or [""])[0]).strip()
        try:
            network = AgentPublicNetworkRepository(backend()).get(agent_id, resolve_dns=True)
            self.send_json(200, {"agent_id": agent_id, "public_network": network})
        except LookupError as exc:
            self.send_json(404, {"error": "not_found", "message": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": "invalid_request", "message": str(exc)})

    def post(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_post(self)
        user = require_manager(self)
        if user is None:
            return
        try:
            body = self.read_json_body()
            agent_id = str(body.get("agent_id") or "").strip()
            network = AgentPublicNetworkRepository(backend()).set(
                agent_id,
                {
                    "public_hostname": body.get("public_hostname"),
                    "public_ipv4": body.get("public_ipv4"),
                },
                actor=str(user.get("username") or "dashboard"),
            )
            self.send_json(200, {"agent_id": agent_id, "public_network": network})
        except LookupError as exc:
            self.send_json(404, {"error": "not_found", "message": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            self.send_json(500, {"error": "public_network_failed", "message": "Não foi possível atualizar a rede pública do Agent."})

    legacy.DashboardHandler.do_GET = get
    legacy.DashboardHandler.do_POST = post


__all__ = ["PATH", "install_agent_public_network"]
