#!/usr/bin/env python3
"""Restricted journal follower for Capivara game-instance units.

The unprivileged Agent never receives generic journal access. This root helper
exposes MESSAGE metadata for capivara-instance-*.service units and byte counts
for protected instance roots over an Agent-only Unix socket.
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
import stat
import time
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


def _instance_unit(payload: dict) -> tuple[str, re.Match[str] | None]:
    # Application stdout/stderr normally identifies the owning unit through
    # _SYSTEMD_UNIT. Messages emitted by systemd itself during stop/start use
    # UNIT or OBJECT_SYSTEMD_UNIT while _SYSTEMD_UNIT points at the manager.
    # Accept only values that still pass the strict Capivara instance allowlist.
    for key in ("OBJECT_SYSTEMD_UNIT", "UNIT", "_SYSTEMD_UNIT"):
        unit = str(payload.get(key) or "").strip()
        match = UNIT_RE.fullmatch(unit)
        if match is not None:
            return unit, match
    return "", None


def _event(payload: dict) -> dict | None:
    unit, match = _instance_unit(payload)
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


INSTANCE_ROOT = Path("/var/lib/capivara-instances")
_STORAGE_SCAN = threading.Lock()


def _instance_storage_bytes(instance_id: str) -> int | None:
    if instance_id in {".", ".."} or UNIT_RE.fullmatch(f"capivara-instance-{instance_id}.service") is None:
        return None
    if not _STORAGE_SCAN.acquire(blocking=False):
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    deadline = time.monotonic() + 1.5

    def scan_error(error: OSError) -> None:
        raise error

    try:
        root_fd = os.open(INSTANCE_ROOT, flags)
        try:
            parent = os.fstat(root_fd)
            if parent.st_uid != 0 or parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return None
            instance_fd = os.open(instance_id, flags, dir_fd=root_fd)
        finally:
            os.close(root_fd)
        try:
            owner = pwd.getpwnam("capivara-instance")
            group = grp.getgrnam("capivara-agent")
            info = os.fstat(instance_fd)
            if (info.st_uid != owner.pw_uid or info.st_gid != group.gr_gid
                    or stat.S_IMODE(info.st_mode) not in (0o700, 0o710)):
                return None
            total = entries = 0
            for _, dirs, files, fd in os.fwalk(
                ".", dir_fd=instance_fd, follow_symlinks=False, onerror=scan_error,
            ):
                entries += len(dirs) + len(files)
                if (entries > 200000 or time.monotonic() >= deadline
                        or os.fstat(fd).st_dev != info.st_dev):
                    return None
                for name in files:
                    if time.monotonic() >= deadline:
                        return None
                    entry = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISREG(entry.st_mode):
                        total += entry.st_size
            return total
        finally:
            os.close(instance_fd)
    except (OSError, KeyError, RecursionError):
        return None
    finally:
        _STORAGE_SCAN.release()


def _handle(connection: socket.socket, allowed_uid: int) -> None:
    with connection:
        peer_uid = _peer_uid(connection)
        if peer_uid is not None and peer_uid != allowed_uid:
            return
        try:
            request = _read_request(connection)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return
        operation = str(request.get("operation") or "").strip().lower()
        if operation == "follow":
            _follow(connection)
        elif operation == "storage_usage" and peer_uid == allowed_uid:
            used = _instance_storage_bytes(str(request.get("instance_id") or ""))
            try:
                connection.sendall(json.dumps({"used_bytes": used}).encode("utf-8") + b"\n")
            except OSError:
                pass


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
