#!/usr/bin/env python3
"""Local-only Palworld game-console bridge backed by the official REST API.

The REST management port never leaves the Agent. Authentication is read from
PalWorldSettings.ini owned by the instance; the password is never returned,
logged, persisted in command results, or placed in argv.
"""
from __future__ import annotations

import base64
import http.client
import json
import re
from pathlib import Path
from typing import Any

_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_OUTPUT_LINES = 200


class PalworldConsoleError(RuntimeError):
    pass


def _option_value(text: str, key: str) -> str | None:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*(?:\"((?:\\.|[^\"])*)\"|([^,)]*))"
    )
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1) if match.group(1) is not None else match.group(2)
    return str(value or "").strip()


def _settings(record: dict[str, Any]) -> tuple[Path, str]:
    state_root = Path(str(record.get("instance_state_root") or "")).resolve()
    config_root = Path(str(record.get("configuration_root") or "")).resolve()
    if not state_root.is_absolute() or not config_root.is_absolute():
        raise PalworldConsoleError("Palworld runtime has no trusted configuration root")
    try:
        config_root.relative_to(state_root)
    except ValueError as exc:
        raise PalworldConsoleError("Palworld configuration is outside instance storage") from exc
    path = (config_root / "PalWorldSettings.ini").resolve()
    try:
        path.relative_to(config_root)
    except ValueError as exc:
        raise PalworldConsoleError("Palworld settings path is outside instance configuration") from exc
    if path.is_symlink() or not path.is_file():
        raise PalworldConsoleError("PalWorldSettings.ini is not available for this instance")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PalworldConsoleError("PalWorldSettings.ini cannot be read by the Agent") from exc
    return path, text


def _rest_port(record: dict[str, Any]) -> int:
    ports = record.get("ports") if isinstance(record.get("ports"), dict) else {}
    binding = ports.get("rest_api") if isinstance(ports.get("rest_api"), dict) else {}
    if str(binding.get("protocol") or "").lower() != "tcp":
        raise PalworldConsoleError("Palworld REST API has no trusted TCP port reservation")
    try:
        port = int(binding.get("port"))
    except (TypeError, ValueError) as exc:
        raise PalworldConsoleError("Palworld REST API port reservation is invalid") from exc
    if not 1 <= port <= 65535:
        raise PalworldConsoleError("Palworld REST API port reservation is invalid")
    return port


def _credentials(record: dict[str, Any]) -> tuple[int, str]:
    _path, text = _settings(record)
    enabled = str(_option_value(text, "RESTAPIEnabled") or "").lower()
    if enabled != "true":
        raise PalworldConsoleError("Palworld REST API is disabled; restart the instance after Capivara applies RESTAPIEnabled=True")
    password = _option_value(text, "AdminPassword") or ""
    if not password:
        raise PalworldConsoleError(
            "Palworld AdminPassword is not configured; set it in PalWorldSettings.ini and restart the instance"
        )
    return _rest_port(record), password


def _request(record: dict[str, Any], method: str, endpoint: str, body: dict[str, Any] | None = None) -> Any:
    port, password = _credentials(record)
    token = base64.b64encode(("admin:" + password).encode("utf-8")).decode("ascii")
    payload = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json", "Authorization": "Basic " + token}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        connection.request(method, "/v1/api/" + endpoint, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read(_MAX_RESPONSE_BYTES + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise PalworldConsoleError(
            "Palworld REST API is unavailable on localhost; confirm the instance was restarted after enabling the API"
        ) from exc
    finally:
        connection.close()
    if len(data) > _MAX_RESPONSE_BYTES:
        raise PalworldConsoleError("Palworld REST API response exceeded the safe limit")
    if response.status == 401:
        raise PalworldConsoleError("Palworld REST API rejected AdminPassword; verify PalWorldSettings.ini and restart the instance")
    if not 200 <= response.status < 300:
        detail = data.decode("utf-8", errors="replace").strip()[:500]
        raise PalworldConsoleError(f"Palworld REST API returned HTTP {response.status}" + (f": {detail}" if detail else ""))
    if not data:
        return None
    text = data.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _output(value: Any, success: str) -> list[str]:
    if value is None or value == "":
        return [success]
    if isinstance(value, str):
        return value.splitlines()[-_MAX_OUTPUT_LINES:] or [success]
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).splitlines()[-_MAX_OUTPUT_LINES:]


def _players_output(value: Any) -> list[str]:
    players = value.get("players") if isinstance(value, dict) else None
    if not isinstance(players, list):
        return _output(value, "Palworld player list returned")
    lines = [f"Players online: {len(players)}"]
    for item in players[:100]:
        if not isinstance(item, dict):
            continue
        fields = [
            str(item.get("name") or item.get("accountName") or "unknown"),
            str(item.get("userId") or ""),
            f"level={item.get('level')}" if item.get("level") is not None else "",
            f"ping={item.get('ping')}" if item.get("ping") is not None else "",
        ]
        lines.append(" · ".join(field for field in fields if field))
    return lines[-_MAX_OUTPUT_LINES:]


def execute(record: dict[str, Any], command: str) -> list[str]:
    if str(record.get("game_id") or "").lower() != "palworld":
        raise PalworldConsoleError("Palworld REST transport cannot execute another game runtime")
    raw = str(command or "").strip()
    if raw.startswith("/"):
        raw = raw[1:].lstrip()
    name, _, rest = raw.partition(" ")
    action = name.lower()
    rest = rest.strip()
    if action == "adminpassword":
        raise PalworldConsoleError("/AdminPassword is blocked in Capivara because credentials must never enter console history")
    if action in {"teleporttoplayer", "teleporttome", "togglespectate"}:
        raise PalworldConsoleError(f"/{name} requires an in-game administrator context and is not exposed by the Palworld REST API")
    if action == "info":
        if rest: raise PalworldConsoleError("Usage: /Info")
        return _output(_request(record, "GET", "info"), "Palworld server info returned")
    if action == "showplayers":
        if rest: raise PalworldConsoleError("Usage: /ShowPlayers")
        return _players_output(_request(record, "GET", "players"))
    if action == "save":
        if rest: raise PalworldConsoleError("Usage: /Save")
        return _output(_request(record, "POST", "save"), "Palworld world saved")
    if action == "broadcast":
        if not rest: raise PalworldConsoleError("Usage: /Broadcast <MessageText>")
        return _output(_request(record, "POST", "announce", {"message": rest}), "Palworld announcement sent")
    if action in {"kickplayer", "banplayer", "unbanplayer"}:
        user_id, _, message = rest.partition(" ")
        if not user_id: raise PalworldConsoleError(f"Usage: /{name} <UserId>")
        endpoint = {"kickplayer": "kick", "banplayer": "ban", "unbanplayer": "unban"}[action]
        body: dict[str, Any] = {"userid": user_id}
        if message and action != "unbanplayer": body["message"] = message
        return _output(_request(record, "POST", endpoint, body), f"Palworld {endpoint} completed")
    if action in {"shutdown", "doexit"}:
        raise PalworldConsoleError(
            f"/{name} is blocked by Capivara lifecycle management; use the Stop action so desired and observed runtime state remain consistent"
        )
    raise PalworldConsoleError(
        "Unsupported Palworld command. Supported by Capivara: /Info, /ShowPlayers, /Save, /Broadcast, /KickPlayer, /BanPlayer, /UnBanPlayer"
    )


__all__ = ["PalworldConsoleError", "execute"]
