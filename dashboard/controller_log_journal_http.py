#!/usr/bin/env python3
"""HTTP composition for journal-only Controller logs."""
from __future__ import annotations

import json
import socket
from urllib.parse import parse_qs, urlparse

PATH = "/api/log-viewer"
SOCKET_PATH = "/run/capivara-controller-log/reader.sock"
MIN_LIMIT = 20
MAX_LIMIT = 2000


def _limit(raw: object) -> int:
    try:
        return max(MIN_LIMIT, min(int(raw), MAX_LIMIT))
    except (TypeError, ValueError):
        return 400


def _read_from_helper(limit: int) -> dict[str, object]:
    request = json.dumps({"operation": "controller_logs", "limit": _limit(limit)}).encode("utf-8") + b"\n"
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
            "source": "controller",
            "backend": "systemd-journal",
            "logs": [],
            "error": "journal_reader_unavailable",
            "message": str(exc),
        }

    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "source": "controller",
            "backend": "systemd-journal",
            "logs": [],
            "error": "journal_reader_invalid_response",
            "message": str(exc),
        }

    if not isinstance(payload, dict):
        return {
            "source": "controller",
            "backend": "systemd-journal",
            "logs": [],
            "error": "journal_reader_invalid_response",
        }

    payload.pop("ok", None)
    payload.setdefault("source", "controller")
    payload.setdefault("backend", "systemd-journal")
    payload.setdefault("logs", [])
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
