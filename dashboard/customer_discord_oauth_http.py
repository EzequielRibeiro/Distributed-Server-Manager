#!/usr/bin/env python3
"""Unauthenticated browser callback for customer Discord OAuth.

The customer's Basic credential lives in sessionStorage and is intentionally
not sent by the browser when Discord redirects back to the Controller. The
callback therefore authenticates the transaction with a short-lived, one-use
OAuth state that was created while the customer was authenticated.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from alert_repository import AlertSession, dialect_for_backend
from customer_audit import audit_customer_event
from customer_discord_http import DISCORD_API, DISCORD_CALLBACK_PATH, DISCORD_TOKEN, MANAGE_GUILD


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _read_secret(value_name: str, file_name: str) -> str:
    value = str(os.environ.get(value_name) or "").strip()
    if value:
        return value
    path = str(os.environ.get(file_name) or "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _config():
    return {
        "client_id": str(os.environ.get("DSM_DISCORD_CLIENT_ID") or "").strip(),
        "redirect_uri": str(os.environ.get("DSM_DISCORD_REDIRECT_URI") or "").strip(),
        "client_secret": _read_secret("DSM_DISCORD_CLIENT_SECRET", "DSM_DISCORD_CLIENT_SECRET_FILE"),
    }


def _json_request(url: str, *, data=None, headers=None):
    body = urlencode(data).encode("utf-8") if isinstance(data, dict) else None
    request = Request(url, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _as_utc(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _redirect(handler, location: str):
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


def _callback(legacy, query: str):
    values = parse_qs(query or "")
    state = str((values.get("state") or [""])[0]).strip()
    code = str((values.get("code") or [""])[0]).strip()
    guild_id_hint = str((values.get("guild_id") or [""])[0]).strip()
    if not state or not code:
        raise ValueError("Discord não retornou uma autorização válida.")

    backend = _backend(legacy)
    ph = dialect_for_backend(backend).placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                f"SELECT state,customer_id,username,expires_at FROM customer_discord_oauth_states WHERE state={ph}",
                (state,),
            ).fetchone()
            if row is None:
                raise ValueError("Autorização Discord inválida ou já utilizada.")
            if _as_utc(row["expires_at"]) < datetime.now(timezone.utc):
                session.execute(f"DELETE FROM customer_discord_oauth_states WHERE state={ph}", (state,))
                connection.commit()
                raise ValueError("A autorização Discord expirou. Inicie a conexão novamente.")
            customer_id = int(row["customer_id"])
            username = str(row["username"])
            session.execute(f"DELETE FROM customer_discord_oauth_states WHERE state={ph}", (state,))
            connection.commit()
        finally:
            session.close()

    config = _config()
    if not all(config.values()):
        raise ValueError("O aplicativo Discord não está configurado no Controller.")
    token = _json_request(
        DISCORD_TOKEN,
        data={
            "client_id": config["client_id"], "client_secret": config["client_secret"],
            "grant_type": "authorization_code", "code": code, "redirect_uri": config["redirect_uri"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    access_token = str(token.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("Discord não forneceu um token de autorização válido.")
    guilds = _json_request(f"{DISCORD_API}/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    manageable = [guild for guild in guilds if int(guild.get("permissions") or 0) & MANAGE_GUILD]
    guild = next((item for item in manageable if str(item.get("id")) == guild_id_hint), None)
    if guild is None and len(manageable) == 1:
        guild = manageable[0]
    if guild is None:
        raise ValueError("A conta Discord administra mais de uma comunidade. Selecione explicitamente a comunidade durante a autorização.")

    connection_id = f"discord-{uuid.uuid4().hex[:20]}"
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            existing = session.execute(
                f"SELECT id FROM customer_discord_connections WHERE customer_id={ph} AND guild_id={ph}",
                (customer_id, str(guild["id"])),
            ).fetchone()
            if existing is not None:
                connection_id = str(existing["id"])
                session.execute(
                    f"UPDATE customer_discord_connections SET guild_name={ph},guild_icon={ph},status='active',updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (str(guild.get("name") or guild["id"]), str(guild.get("icon") or "") or None, connection_id),
                )
            else:
                count = session.execute(
                    f"SELECT COUNT(*) AS n FROM customer_discord_connections WHERE customer_id={ph} AND status='active'",
                    (customer_id,),
                ).fetchone()
                is_default = 1 if int(count["n"] if count is not None else 0) == 0 else 0
                session.execute(
                    f"INSERT INTO customer_discord_connections(id,customer_id,guild_id,guild_name,guild_icon,status,is_default,created_by) VALUES({ph},{ph},{ph},{ph},{ph},'active',{ph},{ph})",
                    (connection_id, customer_id, str(guild["id"]), str(guild.get("name") or guild["id"]), str(guild.get("icon") or "") or None, is_default, username),
                )
            connection.commit()
        finally:
            session.close()

    try:
        audit_customer_event(
            backend, username=username, action="CUSTOMER_DISCORD_CONNECTED", result="success",
            details={"customer_id": customer_id, "connection_id": connection_id, "guild_id": str(guild["id"]), "guild_name": str(guild.get("name") or "")},
        )
    except Exception:
        pass


def install_customer_discord_oauth_callback(legacy):
    previous_get = legacy.DashboardHandler.do_GET

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path != DISCORD_CALLBACK_PATH:
            return previous_get(self)
        try:
            _callback(legacy, parsed.query)
            return _redirect(self, "/customer-integrations.html?discord=connected")
        except Exception as exc:
            message = str(exc) or "Não foi possível conectar o Discord."
            return _redirect(self, "/customer-integrations.html?discord=error&message=" + urlencode({"m": message})[2:])

    legacy.DashboardHandler.do_GET = do_get


__all__ = ["install_customer_discord_oauth_callback"]
