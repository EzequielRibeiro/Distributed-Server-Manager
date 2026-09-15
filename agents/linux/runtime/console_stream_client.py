#!/usr/bin/env python3
"""Persistent outbound console stream from Linux Agent to Controller."""
from __future__ import annotations

from collections import deque
import http.client
import json
import os
import socket
import ssl
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

SOCKET_PATH = os.environ.get("CAPIVARA_AGENT_CONSOLE_READER_SOCKET", "/run/capivara-agent-console/reader.sock")
PUSH_PATH = "/api/agent/console/stream"
MAX_QUEUE = 8192
MAX_BATCH_EVENTS = 16
STREAM_SECONDS = 25.0
KEEPALIVE_SECONDS = 5.0
CONNECT_RETRY_SECONDS = 2.0
MAX_INFLIGHT_EVENTS = 4096
MAX_STREAM_BYTES = 4 * 1024 * 1024
_QUEUE: deque[dict[str, Any]] = deque()
_CONDITION = threading.Condition()
_STARTED = False

def _log(message: str) -> None:
    print(f"console-stream: {message}", file=sys.stderr, flush=True)


def _enqueue(event: dict[str, Any]) -> None:
    with _CONDITION:
        if len(_QUEUE) >= MAX_QUEUE:
            _QUEUE.popleft()
        _QUEUE.append(event)
        _CONDITION.notify_all()


def _take_batch(timeout: float) -> list[dict[str, Any]]:
    deadline = time.monotonic() + max(0.0, timeout)
    with _CONDITION:
        while not _QUEUE:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            _CONDITION.wait(remaining)
        result = []
        while _QUEUE and len(result) < MAX_BATCH_EVENTS:
            result.append(_QUEUE.popleft())
        return result


def _requeue_front(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    with _CONDITION:
        for event in reversed(events):
            if len(_QUEUE) >= MAX_QUEUE:
                _QUEUE.pop()
            _QUEUE.appendleft(event)
        _CONDITION.notify_all()


def _reader_loop() -> None:
    last_error = ""
    while True:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(5)
            client.connect(SOCKET_PATH)
            client.sendall(b'{"operation":"follow"}\n')
            client.settimeout(None)
            stream = client.makefile("rb")
            last_error = ""
            for raw in stream:
                try:
                    value = json.loads(raw.decode("utf-8", errors="replace"))
                except (ValueError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict) and value.get("instance_id") and value.get("cursor") and value.get("line"):
                    _enqueue(value)
        except OSError as exc:
            message = str(exc)
            if message != last_error:
                _log(f"local journal reader unavailable: {message}")
                last_error = message
        finally:
            try:
                client.close()
            except OSError:
                pass
        time.sleep(CONNECT_RETRY_SECONDS)

def _connection(controller_url: str):
    parsed = urlparse(str(controller_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid Controller URL")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        connection = http.client.HTTPSConnection(host, port, timeout=10, context=ssl.create_default_context())
    else:
        connection = http.client.HTTPConnection(host, port, timeout=10)
    base = parsed.path.rstrip("/")
    return connection, (base + PUSH_PATH) or PUSH_PATH


def _headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Content-Type": "application/x-ndjson",
        "Accept": "application/json",
        "Transfer-Encoding": "chunked",
        "User-Agent": "Capivara-Agent-ConsoleStream/1",
        "X-Capivara-Agent-Credential": str(config["credential_id"]),
        "X-Capivara-Agent-Secret": str(config["credential_secret"]),
        "X-Capivara-Agent-Fingerprint": str(config.get("fingerprint") or ""),
    }


def _open_stream(config: dict[str, Any]):
    connection, path = _connection(str(config.get("controller_url") or ""))
    connection.putrequest("POST", path)
    for name, value in _headers(config).items():
        connection.putheader(name, value)
    connection.endheaders()
    if connection.sock is not None:
        connection.sock.settimeout(15)
    return connection


def _frame_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _send_chunk(connection, payload: dict[str, Any]) -> int:
    data = _frame_bytes(payload)
    if len(data) > 256 * 1024:
        raise ValueError("console stream frame exceeds Controller limit")
    connection.send(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")
    return len(data)


def _finish_stream(connection) -> dict[str, Any]:
    connection.send(b"0\r\n\r\n")
    response = connection.getresponse()
    body = response.read(1024 * 1024)
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if response.status != 200:
        raise RuntimeError(str(payload.get("message") or payload.get("error") or f"HTTP {response.status}"))
    return payload if isinstance(payload, dict) else {}

def _sender_loop(config: dict[str, Any]) -> None:
    last_error = ""
    while True:
        connection = None
        inflight: list[dict[str, Any]] = []
        try:
            connection = _open_stream(config)
            started = time.monotonic()
            last_send = started
            sent_bytes = 0
            while True:
                now = time.monotonic()
                if now - started >= STREAM_SECONDS or len(inflight) >= MAX_INFLIGHT_EVENTS or sent_bytes >= MAX_STREAM_BYTES:
                    break
                batch = _take_batch(min(0.25, max(0.0, KEEPALIVE_SECONDS - (now - last_send))))
                if batch:
                    sent_bytes += _send_chunk(connection, {"kind": "console-batch", "events": batch})
                    inflight.extend(batch)
                    last_send = time.monotonic()
                    continue
                if time.monotonic() - last_send >= KEEPALIVE_SECONDS:
                    sent_bytes += _send_chunk(connection, {"kind": "keepalive", "sent_at": time.time()})
                    last_send = time.monotonic()
            _finish_stream(connection)
            inflight.clear()
            if last_error:
                _log("Controller stream recovered")
                last_error = ""
        except Exception as exc:
            _requeue_front(inflight)
            message = str(exc)
            if message != last_error:
                _log(f"Controller stream unavailable: {message}")
                last_error = message
            time.sleep(CONNECT_RETRY_SECONDS)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass


def start_console_stream(config: dict[str, Any]) -> None:
    global _STARTED
    if _STARTED:
        return
    if not config.get("credential_id") or not config.get("credential_secret"):
        return
    _STARTED = True
    threading.Thread(target=_reader_loop, name="capivara-console-journal", daemon=True).start()
    threading.Thread(target=_sender_loop, args=(dict(config),), name="capivara-console-push", daemon=True).start()


__all__ = ["start_console_stream"]
