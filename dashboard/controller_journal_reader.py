#!/usr/bin/env python3
"""Restricted journal reader for Controller services.

This process is the only Dashboard-side component granted membership in
systemd-journal. It exposes a small AF_UNIX protocol to the unprivileged web
process and never accepts unit names or commands from clients.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import struct
import subprocess
from pathlib import Path

JOURNALCTL = "/usr/bin/journalctl"
DEFAULT_SOCKET = "/run/capivara-controller-log/reader.sock"
MAX_REQUEST_BYTES = 4096
MIN_LIMIT = 20
MAX_LIMIT = 2000
CONTROLLER_UNITS = (
    "dsm-dashboard.service",
    "dsm-dashboard-worker.service",
    "dsm-alert-engine.service",
    "dsm-automation-worker.service",
    "dsm-monitor.service",
    "dsm-scheduler.service",
    "dsm-watchdog.service",
)


def clamp_limit(value: object) -> int:
    try:
        return max(MIN_LIMIT, min(int(value), MAX_LIMIT))
    except (TypeError, ValueError):
        return 400


def journal_command(limit: int) -> list[str]:
    command = [
        JOURNALCTL,
        "--quiet",
        "--no-pager",
        "-o",
        "short-iso",
        "-n",
        str(clamp_limit(limit)),
    ]
    for unit in CONTROLLER_UNITS:
        command.extend(("-u", unit))
    return command


INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,190}$")


def instance_unit(instance_id: object) -> str:
    value = str(instance_id or "").strip()
    if not INSTANCE_ID_RE.fullmatch(value):
        raise ValueError("invalid_instance_id")
    return f"capivara-instance-{value}.service"


def read_instance_logs(instance_id: object, limit: int) -> dict[str, object]:
    unit = instance_unit(instance_id)
    try:
        completed = subprocess.run(
            [
                JOURNALCTL,
                "--quiet",
                "--no-pager",
                "-o",
                "short-iso",
                "-n",
                str(clamp_limit(limit)),
                "-u",
                unit,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "error": "journal_unavailable",
            "message": str(exc),
            "logs": [],
        }

    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return {
            "ok": False,
            "error": "journal_read_failed",
            "message": stderr or f"journalctl exited with {completed.returncode}",
            "logs": [],
        }

    lines = (completed.stdout or "").splitlines()
    return {
        "ok": True,
        "source": "instance",
        "instance_id": str(instance_id),
        "backend": "systemd-journal",
        "logs": lines[-clamp_limit(limit):],
        "total_returned": min(len(lines), clamp_limit(limit)),
    }


def read_controller_logs(limit: int) -> dict[str, object]:
    try:
        completed = subprocess.run(
            journal_command(limit),
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "error": "journal_unavailable",
            "message": str(exc),
            "logs": [],
        }

    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return {
            "ok": False,
            "error": "journal_read_failed",
            "message": stderr or f"journalctl exited with {completed.returncode}",
            "logs": [],
        }

    lines = (completed.stdout or "").splitlines()
    return {
        "ok": True,
        "source": "controller",
        "backend": "systemd-journal",
        "logs": lines[-clamp_limit(limit):],
        "total_returned": min(len(lines), clamp_limit(limit)),
    }


def _peer_uid(connection: socket.socket) -> int | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid


def _read_request(connection: socket.socket) -> dict[str, object]:
    data = b""
    while len(data) < MAX_REQUEST_BYTES:
        chunk = connection.recv(min(1024, MAX_REQUEST_BYTES - len(data)))
        if not chunk:
            break
        data += chunk
        if b"\n" in data:
            data = data.split(b"\n", 1)[0]
            break
    if not data:
        raise ValueError("empty_request")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid_request")
    return value


def _reply(connection: socket.socket, payload: dict[str, object]) -> None:
    connection.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")


def serve(socket_path: str) -> None:
    path = Path(socket_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    os.chmod(path, 0o600)
    server.listen(8)

    try:
        while True:
            connection, _ = server.accept()
            with connection:
                peer_uid = _peer_uid(connection)
                if peer_uid is not None and peer_uid != os.getuid():
                    _reply(connection, {"ok": False, "error": "forbidden", "logs": []})
                    continue
                try:
                    request = _read_request(connection)
                    operation = request.get("operation")
                    if operation == "controller_logs":
                        payload = read_controller_logs(
                            clamp_limit(request.get("limit"))
                        )
                    elif operation == "instance_logs":
                        payload = read_instance_logs(
                            request.get("instance_id"),
                            clamp_limit(request.get("limit")),
                        )
                    else:
                        raise ValueError("unsupported_operation")
                    _reply(connection, payload)
                except (ValueError, json.JSONDecodeError) as exc:
                    _reply(connection, {"ok": False, "error": "invalid_request", "message": str(exc), "logs": []})
    finally:
        server.close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    args = parser.parse_args()
    serve(args.socket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
