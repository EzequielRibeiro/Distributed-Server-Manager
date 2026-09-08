#!/usr/bin/env python3
"""HTTP composition and local client for the restricted journal reader."""
from __future__ import annotations

import json
import re
import socket
from urllib.parse import parse_qs, urlparse

PATH = "/api/log-viewer"
SOCKET_PATH = "/run/capivara-controller-log/reader.sock"
MIN_LIMIT = 20
MAX_LIMIT = 2000
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,191}$")


def _limit(raw: object) -> int:
    try:
        return max(MIN_LIMIT, min(int(raw), MAX_LIMIT))
    except (TypeError, ValueError):
        return 400


def _request_helper(payload: dict[str, object]) -> dict[str, object]:
    request = json.dumps(payload).encode("utf-8") + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(SOCKET_PATH)
            client.sendall(request)
            data = b""
            while len(data) < 2 * 1024 * 1024:
                chunk = client.recv(65536)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    data = data.split(b"\n", 1)[0]
                    break
    except OSError as exc:
        return {
            "backend": "systemd-journal",
            "logs": [],
            "error": "journal_reader_unavailable",
            "message": str(exc),
        }

    try:
        response = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "backend": "systemd-journal",
            "logs": [],
            "error": "journal_reader_invalid_response",
            "message": str(exc),
        }

    if not isinstance(response, dict):
        return {
            "backend": "systemd-journal",
            "logs": [],
            "error": "journal_reader_invalid_response",
        }

    response.pop("ok", None)
    response.setdefault("backend", "systemd-journal")
    response.setdefault("logs", [])
    return response


def _read_from_helper(limit: int) -> dict[str, object]:
    payload = _request_helper({"operation": "controller_logs", "limit": _limit(limit)})
    payload.setdefault("source", "controller")
    return payload


def instance_journal_logs(instance_id: str, limit: int = 400) -> dict[str, object]:
    instance_id = str(instance_id or "").strip()
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        return {
            "source": "instance",
            "backend": "systemd-journal",
            "instance_id": instance_id,
            "logs": [],
            "error": "invalid_instance_id",
        }
    payload = _request_helper(
        {
            "operation": "instance_logs",
            "instance_id": instance_id,
            "limit": _limit(limit),
        }
    )
    payload.setdefault("source", "instance")
    payload.setdefault("instance_id", instance_id)
    return payload


def install_controller_log_journal_http(server_module, authenticate) -> None:
    previous_get = server_module.DashboardHandler.do_GET

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path != PATH:
            return previous_get(self)

        query = parse_qs(parsed.query or "")
        source = str((query.get("source") or ["controller"])[0] or "controller").lower()
        if source != "controller":
            return previous_get(self)

        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        if str(user.get("role") or "").lower() != "admin":
            self.send_json(403, {"error": "Somente administradores podem visualizar logs do Controller."})
            return

        result = _read_from_helper(_limit((query.get("limit") or ["400"])[0]))
        status = 200 if not result.get("error") else 503
        self.send_json(status, result)

    server_module.DashboardHandler.do_GET = do_get


__all__ = ["instance_journal_logs", "install_controller_log_journal_http"]
