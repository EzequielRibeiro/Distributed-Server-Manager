#!/usr/bin/env python3
"""Restricted journal reader for Controller and local instance services.

This process is the only Dashboard-side component granted membership in
systemd-journal. It exposes a small AF_UNIX protocol to the unprivileged web
process and never accepts unit names or commands from clients. Instance log
requests accept only a validated instance_id and derive the systemd unit
internally.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

JOURNALCTL = "/usr/bin/journalctl"
DEFAULT_SOCKET = "/run/capivara-controller-log/reader.sock"
MAX_REQUEST_BYTES = 4096
MAX_FOLLOWERS = 64
_FOLLOW_SEMAPHORE = threading.BoundedSemaphore(MAX_FOLLOWERS)
MIN_LIMIT = 20
MAX_LIMIT = 2000
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
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


def instance_journal_command(instance_id: str, limit: int) -> list[str]:
    instance_id = str(instance_id or "").strip()
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError("invalid_instance_id")
    return [
        JOURNALCTL,
        "--quiet",
        "--no-pager",
        "-o",
        "short-iso",
        "-n",
        str(clamp_limit(limit)),
        "--show-cursor",
        "-u",
        f"capivara-instance-{instance_id}.service",
    ]


def instance_follow_command(instance_id: str, after_cursor: str | None = None) -> list[str]:
    instance_id = str(instance_id or "").strip()
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError("invalid_instance_id")
    cursor = str(after_cursor or "").strip()
    if cursor and (len(cursor) > 2048 or "\n" in cursor or "\r" in cursor or "\x00" in cursor):
        raise ValueError("invalid_journal_cursor")
    command = [
        JOURNALCTL,
        "--quiet",
        "--no-pager",
        "-o",
        "short-iso",
        "-n",
        "0",
        "--follow",
    ]
    if cursor:
        command.extend(("--after-cursor", cursor))
    command.extend(("-u", f"capivara-instance-{instance_id}.service"))
    return command


def _run_journal(command: list[str], *, source: str, limit: int, instance_id: str | None = None) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
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
    cursor = None
    if lines and lines[-1].startswith("-- cursor: "):
        cursor = lines.pop()[len("-- cursor: "):].strip() or None
    result: dict[str, object] = {
        "ok": True,
        "source": source,
        "backend": "systemd-journal",
        "logs": lines[-clamp_limit(limit):],
        "total_returned": min(len(lines), clamp_limit(limit)),
    }
    if cursor is not None:
        result["cursor"] = cursor
    if instance_id is not None:
        result["instance_id"] = instance_id
    return result


def read_controller_logs(limit: int) -> dict[str, object]:
    return _run_journal(journal_command(limit), source="controller", limit=limit)


def read_instance_logs(instance_id: str, limit: int) -> dict[str, object]:
    instance_id = str(instance_id or "").strip()
    command = instance_journal_command(instance_id, limit)
    return _run_journal(command, source="instance", limit=limit, instance_id=instance_id)


def follow_instance_logs(connection: socket.socket, instance_id: str, timeout: int = 25, after_cursor: str | None = None) -> None:
    instance_id = str(instance_id or "").strip()
    timeout = max(5, min(int(timeout), 30))
    command = instance_follow_command(instance_id, after_cursor)
    if not _FOLLOW_SEMAPHORE.acquire(blocking=False):
        _reply(connection, {"ok": False, "error": "journal_stream_capacity"})
        return
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        _FOLLOW_SEMAPHORE.release()
        _reply(connection, {"ok": False, "error": "journal_unavailable", "message": str(exc)})
        return
    deadline = time.monotonic() + timeout
    last_keepalive = time.monotonic()
    try:
        _reply(connection, {"ok": True, "stream": True, "source": "instance", "backend": "systemd-journal", "instance_id": instance_id})
        assert process.stdout is not None
        while time.monotonic() < deadline:
            remaining = max(0.0, min(1.0, deadline - time.monotonic()))
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if readable:
                line = process.stdout.readline()
                if line:
                    _reply(connection, {"kind": "line", "line": line.rstrip("\r\n")})
                    continue
                if process.poll() is not None:
                    break
            now = time.monotonic()
            if now - last_keepalive >= 10:
                _reply(connection, {"kind": "keepalive"})
                last_keepalive = now
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        _FOLLOW_SEMAPHORE.release()


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


def _handle_connection(connection: socket.socket) -> None:
    with connection:
        peer_uid = _peer_uid(connection)
        if peer_uid is not None and peer_uid != os.getuid():
            _reply(connection, {"ok": False, "error": "forbidden", "logs": []})
            return
        try:
            request = _read_request(connection)
            operation = str(request.get("operation") or "")
            if operation == "controller_logs":
                _reply(connection, read_controller_logs(clamp_limit(request.get("limit"))))
            elif operation == "instance_logs":
                _reply(connection, read_instance_logs(
                    str(request.get("instance_id") or ""),
                    clamp_limit(request.get("limit")),
                ))
            elif operation == "instance_follow":
                follow_instance_logs(
                    connection,
                    str(request.get("instance_id") or ""),
                    int(request.get("timeout") or 25),
                    str(request.get("after_cursor") or "").strip() or None,
                )
            else:
                raise ValueError("unsupported_operation")
        except (ValueError, json.JSONDecodeError) as exc:
            try:
                _reply(connection, {"ok": False, "error": "invalid_request", "message": str(exc), "logs": []})
            except OSError:
                pass


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
    server.listen(32)

    try:
        while True:
            connection, _ = server.accept()
            threading.Thread(target=_handle_connection, args=(connection,), daemon=True).start()
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
