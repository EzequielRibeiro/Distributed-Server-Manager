#!/usr/bin/env python3
"""Administrative and Agent-authenticated API for player-facing public network identity."""
from __future__ import annotations
from urllib.parse import parse_qs, urlparse

from agent_pairing_api import authenticate_agent_identity
from agent_public_network import AgentPublicNetworkRepository

ADMIN_PATH = "/api/admin/agent/public-network"
AGENT_PATH = "/api/agent/public-network"


def install_agent_public_network(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    legacy.STATIC_FILES["/agent-public-network.js"] = legacy.WEB_DIR / "agent-public-network.js"
    legacy.STATIC_FILES["/agent-network-panel.js"] = legacy.WEB_DIR / "agent-network-panel.js"

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

    def require_agent(self):
        credential_id = str(self.headers.get("X-Capivara-Agent-Credential") or "").strip()
        credential_secret = str(self.headers.get("X-Capivara-Agent-Secret") or "").strip()
        fingerprint = str(self.headers.get("X-Capivara-Agent-Fingerprint") or "").strip() or None
        try:
            return authenticate_agent_identity(
                backend(),
                credential_id=credential_id,
                credential_secret=credential_secret,
                fingerprint=fingerprint,
            )
        except PermissionError:
            self.send_json(401, {"error": "unauthorized_agent", "message": "Credencial do Agent inválida."})
            return None

    def get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {ADMIN_PATH, AGENT_PATH}:
            return previous_get(self)
        if parsed.path == AGENT_PATH:
            identity = require_agent(self)
            if identity is None:
                return
            agent_id = str(identity["agent_id"])
        else:
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
        if parsed.path not in {ADMIN_PATH, AGENT_PATH}:
            return previous_post(self)
        if parsed.path == AGENT_PATH:
            identity = require_agent(self)
            if identity is None:
                return
            agent_id = str(identity["agent_id"])
            actor = "agent-local-cli"
        else:
            user = require_manager(self)
            if user is None:
                return
            actor = str(user.get("username") or "dashboard")
            agent_id = ""
        try:
            body = self.read_json_body()
            if parsed.path == ADMIN_PATH:
                agent_id = str(body.get("agent_id") or "").strip()
            network = AgentPublicNetworkRepository(backend()).set(
                agent_id,
                {
                    "public_hostname": body.get("public_hostname"),
                    "public_ipv4": body.get("public_ipv4"),
                },
                actor=actor,
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


PATH = ADMIN_PATH
__all__ = ["ADMIN_PATH", "AGENT_PATH", "PATH", "install_agent_public_network"]
