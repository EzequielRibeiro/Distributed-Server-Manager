#!/usr/bin/env python3
"""Customer-facing player connection endpoint for game instances."""
from __future__ import annotations
from urllib.parse import parse_qs, urlparse

from agent_public_network import AgentPublicNetworkRepository, player_endpoint
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from controller_session import session_user_from_headers

PATH = "/api/customer/instance/connection"
_PRIMARY_NAMES = ("game", "server", "primary", "game_port", "port")


def install_customer_instance_connection(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    legacy.STATIC_FILES["/customer-instance-core.js"] = legacy.WEB_DIR / "customer-instance-v2.js"
    legacy.STATIC_FILES["/customer-instance-v2.js"] = legacy.WEB_DIR / "customer-instance-v2-wrapper.js"
    legacy.STATIC_FILES["/customer-instance-connection.js"] = legacy.WEB_DIR / "customer-instance-connection.js"

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def user_for(self):
        value = session_user_from_headers(self.headers)
        if value is not None:
            return value
        try:
            return authenticate(self.headers)
        except Exception:
            return None

    def primary_port(ports):
        rows = [dict(item) for item in (ports or [])]
        if not rows:
            return None
        for wanted in _PRIMARY_NAMES:
            for row in rows:
                if str(row.get("name") or "").strip().lower() == wanted:
                    return row
        return rows[0]

    def get(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_get(self)
        user = user_for(self)
        if user is None:
            self.unauthorized()
            return
        if str(user.get("role") or "").lower() not in {"customer", "admin", "controller"}:
            self.forbidden()
            return
        instance_id = str((parse_qs(parsed.query).get("instance_id") or [""])[0]).strip()
        try:
            api = CustomerInstanceWorkspaceService(backend(), legacy.DSM_ROOT)
            context = api.require(user, instance_id, "instance.view")
            ports = api._ports(instance_id)
            selected = primary_port(ports)
            network = AgentPublicNetworkRepository(backend()).get(str(context.get("agent_id") or ""), resolve_dns=True)
            effective_network = dict(network)
            dns = network.get("dns") if isinstance(network.get("dns"), dict) else {}
            fallback = False
            if network.get("public_hostname") and str(dns.get("status") or "") != "active" and network.get("public_ipv4"):
                effective_network["public_hostname"] = None
                fallback = True
            protocol = str(selected.get("protocol") or "udp") if selected else "udp"
            endpoint = player_endpoint(
                effective_network,
                selected.get("port") if selected else None,
                protocol=protocol,
            )
            if endpoint is not None:
                endpoint["protocol"] = protocol
                endpoint["port_name"] = selected.get("name")
                endpoint["dns_status"] = dns.get("status")
                endpoint["fallback"] = fallback
            self.send_json(200, {
                "instance_id": instance_id,
                "status": context.get("status"),
                "connection": endpoint,
                "public_network": network,
                "configured": endpoint is not None,
            })
        except PermissionError as exc:
            self.send_json(403, {"error": "forbidden", "message": str(exc)})
        except (KeyError, LookupError):
            self.send_json(404, {"error": "not_found", "message": "Instância não encontrada."})
        except ValueError as exc:
            self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            self.send_json(500, {"error": "connection_failed", "message": "Não foi possível determinar o endereço público do servidor."})

    legacy.DashboardHandler.do_GET = get


__all__ = ["PATH", "install_customer_instance_connection"]
