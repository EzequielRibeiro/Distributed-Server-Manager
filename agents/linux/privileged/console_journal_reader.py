#!/usr/bin/env python3
"""Restricted journal follower for Capivara game-instance units.

The unprivileged Agent never receives generic journal access. This root helper
exposes only MESSAGE metadata for units named capivara-instance-*.service over
a Unix socket owned by the capivara-agent group.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import socket
import struct
import subprocess
import threading

SOCKET_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONSOLE_READER_SOCKET", "/run/capivara-agent-console/reader.sock"))
UNIT_RE = re.compile(r"^capivara-instance-([A-Za-z0-9._-]{1,191})\.service$")
MAX_REQUEST_BYTES = 4096
MAX_MESSAGE_BYTES = 8192

def _peer_uid(connection: socket.socket) -> int | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid


def _read_request(connection: socket.socket) -> dict:
    data = b""
    while len(data) < MAX_REQUEST_BYTES:
        chunk = connection.recv(min(1024, MAX_REQUEST_BYTES - len(data)))
        if not chunk:
            break
        data += chunk
        if b"\n" in data:
            data = data.split(b"\n", 1)[0]
            break
    value = json.loads(data.decode("utf-8")) if data else {}
    if not isinstance(value, dict):
        raise ValueError("invalid request")
    return value


def _cursor(unit: str, payload: dict, message: str) -> str:
    value = str(payload.get("__CURSOR") or "").strip()
    if value:
        return value[:1024]
    material = "\n".join([unit, str(payload.get("__REALTIME_TIMESTAMP") or ""), message]).encode("utf-8")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _event(payload: dict) -> dict | None:
    unit = str(payload.get("_SYSTEMD_UNIT") or "")
    match = UNIT_RE.fullmatch(unit)
    if match is None:
        return None
    message = str(payload.get("MESSAGE") or "").replace("\x00", "")[:MAX_MESSAGE_BYTES]
    if not message:
        return None
    return {
        "instance_id": match.group(1),
        "cursor": _cursor(unit, payload, message),
        "line": message,
        "priority": str(payload.get("PRIORITY") or "")[:16] or None,
        "timestamp": str(payload.get("__REALTIME_TIMESTAMP") or "")[:64] or None,
    }

def _follow(connection: socket.socket) -> None:
    command = [
        "journalctl",
        "--follow",
        "--lines=0",
        "--no-pager",
        "--output=json",
        "--unit=capivara-instance-*.service",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        text=False,
        bufsize=0,
    )
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace"))
            except (ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            event = _event(payload)
            if event is None:
                continue
            try:
                connection.sendall(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                break
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


def _handle(connection: socket.socket, allowed_uid: int) -> None:
    with connection:
        peer_uid = _peer_uid(connection)
        if peer_uid is not None and peer_uid != allowed_uid:
            return
        try:
            request = _read_request(connection)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if str(request.get("operation") or "").strip().lower() != "follow":
            return
        _follow(connection)

def serve_forever() -> None:
    account = pwd.getpwnam("capivara-agent")
    group = grp.getgrnam("capivara-agent")
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chown(SOCKET_PATH.parent, 0, group.gr_gid)
        os.chmod(SOCKET_PATH.parent, 0o750)
    except OSError:
        pass
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(SOCKET_PATH))
        os.chown(SOCKET_PATH, 0, group.gr_gid)
        os.chmod(SOCKET_PATH, 0o660)
        listener.listen(4)
        while True:
            connection, _ = listener.accept()
            thread = threading.Thread(target=_handle, args=(connection, account.pw_uid), daemon=True)
            thread.start()
    finally:
        listener.close()
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    serve_forever()
