#!/usr/bin/env python3
"""Customer-facing player connection endpoint for game instances."""
from __future__ import annotations
from pathlib import Path
import json
from urllib.parse import parse_qs, quote, urlparse

from agent_public_network import AgentPublicNetworkRepository, player_endpoint
from agent_runtime_repository import AgentRuntimeRepository
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from controller_session import session_user_from_headers
from steam_query import SteamQueryError, query_steam_a2s

PATH = "/api/customer/instance/connection"
TEST_PATH = PATH + "/test"
_PRIMARY_NAMES = ("game", "game_ipv4", "game_udp", "server", "primary", "game_port", "port")


def _query_profile(root: Path, game_id: str, runtime_id: str) -> dict:
    path = Path(root) / "catalog" / "v2" / "external-query-compatibility.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    games = payload.get("games") if isinstance(payload, dict) else {}
    base = games.get(str(game_id or "").strip().lower()) if isinstance(games, dict) else None
    if not isinstance(base, dict):
        return {}
    result = {key: value for key, value in base.items() if key != "runtime_overrides"}
    overrides = base.get("runtime_overrides")
    override = overrides.get(str(runtime_id or "")) if isinstance(overrides, dict) else None
    if isinstance(override, dict):
        result.update(override)
    return result


def _listening_ports(runtime: dict, ports: list[dict]) -> list[dict]:
    network = runtime.get("network") if isinstance(runtime.get("network"), dict) else {}
    online = str(runtime.get("health_status") or "").strip().lower() == "online"
    complete = {
        "tcp": network.get("tcp_complete") is True,
        "udp": network.get("udp_complete") is True,
    }
    observed = {
        "tcp": {int(value) for value in network.get("tcp_listen") or [] if str(value).isdigit()},
        "udp": {int(value) for value in network.get("udp_listen") or [] if str(value).isdigit()},
    }
    result = []
    for raw in ports:
        item = dict(raw)
        protocol = str(item.get("protocol") or "").strip().lower()
        try:
            port = int(item.get("port"))
        except (TypeError, ValueError):
            port = 0
        if protocol in observed and port in observed[protocol]:
            item["state"] = "listening"
        elif not online or not complete.get(protocol):
            item["state"] = "unknown"
        else:
            item["state"] = "reserved"
        result.append(item)
    return result


def _query_target(profile: dict, ports: list[dict], network: dict) -> dict | None:
    if not profile or not network:
        return None
    by_name = {str(item.get("name") or ""): item for item in ports}
    strategy = str(profile.get("strategy") or "")
    role = str(profile.get("query_role") or "") if strategy in {"offset", "fixed_default_query", "direct_query_role"} else str(profile.get("game_role") or "")
    selected = by_name.get(role)
    if not selected:
        return None
    try:
        port = int(selected.get("port"))
    except (TypeError, ValueError):
        return None
    selected_protocol = str(selected.get("protocol") or "udp").strip().lower()
    public_endpoint = player_endpoint(network, port, protocol=selected_protocol)
    if public_endpoint is None:
        return None
    target = str(public_endpoint.get("address") or "").strip()
    if not target:
        return None
    return {
        "role": role,
        "port": port,
        "protocol": selected_protocol,
        "endpoint": public_endpoint,
        "target": target,
    }


def _external_query_check(profile: dict, ports: list[dict], network: dict) -> dict | None:
    target = _query_target(profile, ports, network)
    if target is None:
        return None
    game_type = str(profile.get("gamedig_type") or "").strip()
    checker_type = str(profile.get("checker_type") or game_type).strip()
    if not game_type or not checker_type:
        return None
    native_steam = checker_type == "valve"
    payload = {
        "provider": "capivara-steam-query" if native_steam else "ismygameserver.online",
        "native": native_steam,
        "gamedig_type": game_type,
        "checker_type": checker_type,
        "protocol": profile.get("protocol"),
        "strategy": str(profile.get("strategy") or ""),
        "port_role": target["role"],
        "port": target["port"],
        "target": target["target"],
        "bind_port": target["port"],
        "public_port": target["endpoint"].get("public_port"),
        "status": str(profile.get("status") or "supported"),
        "note": profile.get("note"),
    }
    if native_steam:
        payload["test_url"] = TEST_PATH
    else:
        payload["url"] = f"https://ismygameserver.online/{quote(checker_type, safe='')}/{quote(target['target'], safe=':[]')}"
    return payload


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
        if parsed.path not in {PATH, TEST_PATH}:
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

            try:
                runtime = AgentRuntimeRepository(backend()).snapshot(
                    str(context.get("agent_id") or ""),
                    refresh_health=False,
                )
            except Exception:
                runtime = {}
            port_status = _listening_ports(runtime, ports)

            query_profile = _query_profile(
                Path(legacy.DSM_ROOT),
                str(context.get("game_id") or ""),
                str(context.get("runtime_id") or ""),
            )
            labels = query_profile.get("port_labels") if isinstance(query_profile.get("port_labels"), dict) else {}
            for item in port_status:
                label = labels.get(str(item.get("name") or ""))
                if label:
                    item["label"] = str(label)
            external_check = _external_query_check(query_profile, port_status, effective_network)

            if parsed.path == TEST_PATH:
                if not external_check or not external_check.get("native"):
                    self.send_json(400, {"error": "native_query_unavailable", "message": "O teste nativo Steam Query não está disponível para este jogo."})
                    return
                target = _query_target(query_profile, port_status, effective_network)
                if target is None:
                    self.send_json(400, {"error": "query_target_unavailable", "message": "A porta pública de query não está disponível."})
                    return
                try:
                    result = query_steam_a2s(
                        str(target["endpoint"].get("host") or ""),
                        int(target["endpoint"].get("public_port") or target["port"]),
                        timeout=3.0,
                    )
                except SteamQueryError as exc:
                    self.send_json(200, {
                        "online": False,
                        "target": target["target"],
                        "port_role": target["role"],
                        "message": str(exc)[:300],
                    })
                    return
                result["target"] = target["target"]
                result["port_role"] = target["role"]
                self.send_json(200, result)
                return

            self.send_json(200, {
                "instance_id": instance_id,
                "status": context.get("status"),
                "connection": endpoint,
                "public_network": network,
                "ports": port_status,
                "external_query": external_check,
                "agent_health": runtime.get("health_status"),
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


__all__ = ["PATH", "TEST_PATH", "install_customer_instance_connection"]
