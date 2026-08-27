#!/usr/bin/env python3
"""Generic Discord integration for authenticated customer accounts.

Discord is a Capivara integration, never a game-specific integration. A customer
may define a default guild and override/disable it per instance.
"""
from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from alert_repository import AlertSession, dialect_for_backend
from customer_audit import audit_customer_event

DISCORD_PATH = "/api/customer/integrations/discord"
DISCORD_CALLBACK_PATH = "/api/customer/integrations/discord/callback"
DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN = "https://discord.com/api/v10/oauth2/token"
DISCORD_API = "https://discord.com/api/v10"
MANAGE_GUILD = 0x20

DEFAULT_EVENTS = (
    "server.started", "server.stopped", "server.crashed", "player.connected",
    "player.disconnected", "backup.completed", "backup.failed", "alert.critical",
)
DEFAULT_COMMANDS = ("status", "players", "start", "stop", "restart", "backup", "serverinfo", "events")


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _ph(backend):
    return dialect_for_backend(backend).placeholder


def _read_secret(value_name: str, file_name: str) -> str:
    direct = str(os.environ.get(value_name) or "").strip()
    if direct:
        return direct
    path = str(os.environ.get(file_name) or "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _oauth_config():
    client_id = str(os.environ.get("DSM_DISCORD_CLIENT_ID") or "").strip()
    redirect_uri = str(os.environ.get("DSM_DISCORD_REDIRECT_URI") or "").strip()
    client_secret = _read_secret("DSM_DISCORD_CLIENT_SECRET", "DSM_DISCORD_CLIENT_SECRET_FILE")
    bot_token = _read_secret("DSM_DISCORD_BOT_TOKEN", "DSM_DISCORD_BOT_TOKEN_FILE")
    return {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "client_secret": client_secret,
        "bot_configured": bool(bot_token),
        "configured": bool(client_id and redirect_uri and client_secret),
    }


def _identity(user):
    if not user or str(user.get("role") or "").lower() != "customer":
        raise PermissionError("customer authentication required")
    customer_id = int(user.get("customer_id") or user.get("scope_id") or 0)
    if customer_id <= 0:
        raise PermissionError("customer scope required")
    return customer_id, str(user.get("username") or "customer")


def _rows(rows):
    result = []
    for row in rows:
        try:
            result.append(dict(row))
        except Exception:
            result.append({key: row[key] for key in row.keys()})
    return result


def _json_request(url: str, *, data=None, headers=None):
    body = urlencode(data).encode("utf-8") if isinstance(data, dict) else None
    request = Request(url, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _begin_oauth(backend, customer_id: int, username: str):
    config = _oauth_config()
    if not config["configured"]:
        return None
    state = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    ph = _ph(backend)
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            session.execute(
                f"INSERT INTO customer_discord_oauth_states(state,customer_id,username,expires_at) VALUES({ph},{ph},{ph},{ph})",
                (state, customer_id, username, expires.isoformat()),
            )
            connection.commit()
        finally:
            session.close()
    query = urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": "identify guilds bot applications.commands",
        "permissions": "0",
        "state": state,
        "prompt": "consent",
    })
    return f"{DISCORD_AUTHORIZE}?{query}"


def discord_snapshot(*, user, backend):
    try:
        customer_id, username = _identity(user)
        ph = _ph(backend)
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                connections = _rows(session.execute(
                    f"SELECT id,guild_id,guild_name,guild_icon,status,is_default,created_at,updated_at FROM customer_discord_connections WHERE customer_id={ph} ORDER BY is_default DESC,guild_name",
                    (customer_id,),
                ).fetchall())
                bindings = _rows(session.execute(
                    f"SELECT customer_id,instance_id,mode,connection_id,channel_id,channel_name,enabled,updated_at FROM customer_discord_instance_bindings WHERE customer_id={ph} ORDER BY instance_id",
                    (customer_id,),
                ).fetchall())
                preferences = _rows(session.execute(
                    f"SELECT instance_id,preference_type,preference_key,enabled,channel_id,discord_role_id,require_confirmation FROM customer_discord_preferences WHERE customer_id={ph} ORDER BY instance_id,preference_type,preference_key",
                    (customer_id,),
                ).fetchall())
            finally:
                session.close()
        config = _oauth_config()
        oauth_url = _begin_oauth(backend, customer_id, username) if config["configured"] else None
        return 200, {
            "integration": "discord",
            "generic": True,
            "connections": connections,
            "bindings": bindings,
            "preferences": preferences,
            "catalog": {"events": DEFAULT_EVENTS, "commands": DEFAULT_COMMANDS},
            "oauth": {"configured": config["configured"], "bot_configured": config["bot_configured"], "authorize_url": oauth_url},
        }
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except Exception as exc:
        return 500, {"error": "discord_unavailable", "message": "Não foi possível consultar a integração Discord.", "detail": str(exc)}


def _audit(backend, username, customer_id, action, details):
    try:
        audit_customer_event(backend, username=username, action=action, result="success", details={"customer_id": customer_id, **details})
    except Exception:
        pass


def discord_update(payload, *, user, backend):
    body = payload if isinstance(payload, dict) else {}
    action = str(body.get("action") or "").strip()
    try:
        customer_id, username = _identity(user)
        ph = _ph(backend)
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                if action == "set_default":
                    connection_id = str(body.get("connection_id") or "").strip()
                    session.execute(f"UPDATE customer_discord_connections SET is_default=0,updated_at=CURRENT_TIMESTAMP WHERE customer_id={ph}", (customer_id,))
                    cursor = session.execute(f"UPDATE customer_discord_connections SET is_default=1,updated_at=CURRENT_TIMESTAMP WHERE customer_id={ph} AND id={ph}", (customer_id, connection_id))
                    if getattr(cursor, "rowcount", 0) != 1:
                        raise ValueError("Discord connection not found")
                    _audit(backend, username, customer_id, "CUSTOMER_DISCORD_DEFAULT_CHANGED", {"connection_id": connection_id})
                elif action == "disconnect":
                    connection_id = str(body.get("connection_id") or "").strip()
                    session.execute(f"UPDATE customer_discord_connections SET status='revoked',is_default=0,updated_at=CURRENT_TIMESTAMP WHERE customer_id={ph} AND id={ph}", (customer_id, connection_id))
                    session.execute(f"UPDATE customer_discord_instance_bindings SET mode='inherit',connection_id=NULL,updated_at=CURRENT_TIMESTAMP WHERE customer_id={ph} AND connection_id={ph}", (customer_id, connection_id))
                    _audit(backend, username, customer_id, "CUSTOMER_DISCORD_DISCONNECTED", {"connection_id": connection_id})
                elif action == "set_binding":
                    instance_id = str(body.get("instance_id") or "").strip()
                    mode = str(body.get("mode") or "inherit").strip()
                    connection_id = str(body.get("connection_id") or "").strip() or None
                    channel_id = str(body.get("channel_id") or "").strip() or None
                    channel_name = str(body.get("channel_name") or "").strip() or None
                    if not instance_id or mode not in {"inherit", "connection", "disabled"}:
                        raise ValueError("invalid instance binding")
                    if mode == "connection" and not connection_id:
                        raise ValueError("connection_id is required")
                    session.execute(f"DELETE FROM customer_discord_instance_bindings WHERE customer_id={ph} AND instance_id={ph}", (customer_id, instance_id))
                    session.execute(
                        f"INSERT INTO customer_discord_instance_bindings(customer_id,instance_id,mode,connection_id,channel_id,channel_name,enabled) VALUES({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                        (customer_id, instance_id, mode, connection_id, channel_id, channel_name, 0 if mode == "disabled" else 1),
                    )
                    _audit(backend, username, customer_id, "CUSTOMER_DISCORD_INSTANCE_BINDING_CHANGED", {"instance_id": instance_id, "mode": mode, "connection_id": connection_id})
                elif action == "set_preference":
                    instance_id = str(body.get("instance_id") or "*").strip() or "*"
                    pref_type = str(body.get("type") or "").strip()
                    key = str(body.get("key") or "").strip()
                    if pref_type not in {"event", "command"} or not key:
                        raise ValueError("invalid preference")
                    if pref_type == "event" and key not in DEFAULT_EVENTS:
                        raise ValueError("unsupported generic event")
                    if pref_type == "command" and key not in DEFAULT_COMMANDS:
                        raise ValueError("unsupported generic command")
                    session.execute(f"DELETE FROM customer_discord_preferences WHERE customer_id={ph} AND instance_id={ph} AND preference_type={ph} AND preference_key={ph}", (customer_id, instance_id, pref_type, key))
                    session.execute(
                        f"INSERT INTO customer_discord_preferences(customer_id,instance_id,preference_type,preference_key,enabled,channel_id,discord_role_id,require_confirmation) VALUES({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                        (customer_id, instance_id, pref_type, key, 1 if body.get("enabled", True) else 0, str(body.get("channel_id") or "").strip() or None, str(body.get("discord_role_id") or "").strip() or None, 1 if body.get("require_confirmation") else 0),
                    )
                    _audit(backend, username, customer_id, "CUSTOMER_DISCORD_PREFERENCE_CHANGED", {"instance_id": instance_id, "type": pref_type, "key": key})
                else:
                    return 400, {"error": "invalid_action", "message": "Ação Discord inválida."}
                connection.commit()
            finally:
                session.close()
        return discord_snapshot(user=user, backend=backend)
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception as exc:
        return 500, {"error": "discord_update_failed", "message": "Não foi possível atualizar a integração Discord.", "detail": str(exc)}


def discord_callback(query: str, *, user, backend):
    values = parse_qs(query or "")
    state = str((values.get("state") or [""])[0]).strip()
    code = str((values.get("code") or [""])[0]).strip()
    guild_id_hint = str((values.get("guild_id") or [""])[0]).strip()
    if not state or not code:
        return 400, {"error": "invalid_oauth_callback", "message": "Discord não retornou uma autorização válida."}
    try:
        customer_id, username = _identity(user)
        config = _oauth_config()
        if not config["configured"]:
            raise ValueError("Discord OAuth is not configured")
        ph = _ph(backend)
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                row = session.execute(f"SELECT state,customer_id,username,expires_at FROM customer_discord_oauth_states WHERE state={ph} AND customer_id={ph}", (state, customer_id)).fetchone()
                if row is None:
                    raise ValueError("invalid OAuth state")
                expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
                if expires < datetime.now(timezone.utc):
                    raise ValueError("expired OAuth state")
                session.execute(f"DELETE FROM customer_discord_oauth_states WHERE state={ph}", (state,))
                connection.commit()
            finally:
                session.close()
        token = _json_request(DISCORD_TOKEN, data={
            "client_id": config["client_id"], "client_secret": config["client_secret"],
            "grant_type": "authorization_code", "code": code, "redirect_uri": config["redirect_uri"],
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        access_token = str(token.get("access_token") or "")
        guilds = _json_request(f"{DISCORD_API}/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"})
        manageable = [g for g in guilds if int(g.get("permissions") or 0) & MANAGE_GUILD]
        guild = next((g for g in manageable if str(g.get("id")) == guild_id_hint), None)
        if guild is None and len(manageable) == 1:
            guild = manageable[0]
        if guild is None:
            raise ValueError("Não foi possível determinar o servidor Discord autorizado; selecione um servidor administrável.")
        connection_id = f"discord-{uuid.uuid4().hex[:20]}"
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                existing = session.execute(f"SELECT id FROM customer_discord_connections WHERE customer_id={ph} AND guild_id={ph}", (customer_id, str(guild["id"]))).fetchone()
                if existing is not None:
                    connection_id = str(existing["id"])
                    session.execute(f"UPDATE customer_discord_connections SET guild_name={ph},guild_icon={ph},status='active',updated_at=CURRENT_TIMESTAMP WHERE id={ph}", (str(guild.get("name") or guild["id"]), str(guild.get("icon") or "") or None, connection_id))
                else:
                    count = session.execute(f"SELECT COUNT(*) AS n FROM customer_discord_connections WHERE customer_id={ph} AND status='active'", (customer_id,)).fetchone()
                    is_default = 1 if int(count["n"] if count is not None else 0) == 0 else 0
                    session.execute(f"INSERT INTO customer_discord_connections(id,customer_id,guild_id,guild_name,guild_icon,status,is_default,created_by) VALUES({ph},{ph},{ph},{ph},{ph},'active',{ph},{ph})", (connection_id, customer_id, str(guild["id"]), str(guild.get("name") or guild["id"]), str(guild.get("icon") or "") or None, is_default, username))
                connection.commit()
            finally:
                session.close()
        _audit(backend, username, customer_id, "CUSTOMER_DISCORD_CONNECTED", {"connection_id": connection_id, "guild_id": str(guild["id"]), "guild_name": str(guild.get("name") or "")})
        return 200, {"connected": True, "connection_id": connection_id, "guild": {"id": str(guild["id"]), "name": str(guild.get("name") or "")}}
    except Exception as exc:
        return 400, {"error": "discord_oauth_failed", "message": str(exc)}


def install_customer_discord(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {DISCORD_PATH, DISCORD_CALLBACK_PATH}:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        backend = _backend(legacy)
        if parsed.path == DISCORD_CALLBACK_PATH:
            status, payload = discord_callback(parsed.query, user=user, backend=backend)
            if status == 200:
                self.send_response(302)
                self.send_header("Location", "/customer-integrations.html?discord=connected")
                self.end_headers(); return
            self.send_json(status, payload); return
        status, payload = discord_snapshot(user=user, backend=backend)
        self.send_json(status, payload)

    def do_post(self):
        if urlparse(self.path).path != DISCORD_PATH:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        try:
            body = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."}); return
        status, payload = discord_update(body, user=user, backend=_backend(legacy))
        self.send_json(status, payload)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = ["DISCORD_PATH", "DISCORD_CALLBACK_PATH", "discord_snapshot", "discord_update", "install_customer_discord"]
