#!/usr/bin/env python3
"""Low-latency Agent -> Controller console push transport.

Remote Agents keep an outbound, chunked HTTP request open and send bounded
NDJSON micro-batches. The Controller keeps only a short in-memory ring; the
canonical journal/heartbeat paths remain fallbacks and restart recovery.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import re
import socket
import threading
import time
from typing import Any

from agent_pairing_repository import AgentCredentialInvalid, AgentPairingRepository
from instance_workspace_repository import InstanceWorkspaceRepository

CONSOLE_PUSH_PATH = "/api/agent/console/stream"
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
MAX_FRAME_BYTES = 256 * 1024
MAX_CONNECTION_BYTES = 8 * 1024 * 1024
MAX_EVENTS_PER_FRAME = 128
RING_LINES = 2000
SEEN_CURSORS = 4096
FRESH_SECONDS = 20.0
_LOCK = threading.RLock()
_BUFFERS: dict[str, dict[str, Any]] = {}
_AGENT_SEEN: dict[str, float] = {}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _buffer(instance_id: str, agent_id: str) -> dict[str, Any]:
    current = _BUFFERS.get(instance_id)
    if current is None or current.get("agent_id") != agent_id:
        current = {
            "agent_id": agent_id,
            "lines": deque(maxlen=RING_LINES),
            "seen_order": deque(maxlen=SEEN_CURSORS),
            "seen": set(),
            "updated_at": None,
        }
        _BUFFERS[instance_id] = current
    return current


def _remember_cursor(state: dict[str, Any], cursor: str) -> bool:
    seen: set[str] = state["seen"]
    if cursor in seen:
        return False
    order: deque[str] = state["seen_order"]
    if len(order) == order.maxlen and order:
        seen.discard(order[0])
    order.append(cursor)
    seen.add(cursor)
    return True


def touch_agent(agent_id: str) -> None:
    with _LOCK:
        _AGENT_SEEN[str(agent_id)] = time.monotonic()


def _owned_instances(agent_id: str, instance_ids: set[str], backend) -> set[str]:
    repo = InstanceWorkspaceRepository(backend)
    repo.initialize()
    allowed: set[str] = set()
    for instance_id in instance_ids:
        try:
            context = repo.instance_context(instance_id)
        except (KeyError, ValueError, LookupError):
            continue
        if str(context.get("agent_id") or "") == agent_id:
            allowed.add(instance_id)
    return allowed

def ingest_console_events(agent_id: str, events: list[dict[str, Any]], *, backend) -> dict[str, int]:
    agent_id = str(agent_id or "").strip()
    candidates: list[dict[str, Any]] = []
    instance_ids: set[str] = set()
    rejected = 0
    for raw in (events or [])[:MAX_EVENTS_PER_FRAME]:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        instance_id = str(raw.get("instance_id") or "").strip()
        cursor = str(raw.get("cursor") or "").strip()
        if not INSTANCE_ID_RE.fullmatch(instance_id) or not cursor or len(cursor) > 1024:
            rejected += 1
            continue
        line = str(raw.get("line") or "").replace("\x00", "")[:8192]
        if not line:
            continue
        candidates.append(
            {
                "instance_id": instance_id,
                "cursor": cursor,
                "line": line,
                "priority": str(raw.get("priority") or "")[:16] or None,
                "timestamp": str(raw.get("timestamp") or "")[:64] or None,
            }
        )
        instance_ids.add(instance_id)
    allowed = _owned_instances(agent_id, instance_ids, backend) if instance_ids else set()
    accepted = duplicates = 0
    now = _now_iso()
    with _LOCK:
        _AGENT_SEEN[agent_id] = time.monotonic()
        for event in candidates:
            if event["instance_id"] not in allowed:
                rejected += 1
                continue
            state = _buffer(event["instance_id"], agent_id)
            if not _remember_cursor(state, event["cursor"]):
                duplicates += 1
                continue
            state["lines"].append(
                {
                    "line": event["line"],
                    "source": "agent-push",
                    "cursor": event["cursor"],
                    "priority": event["priority"],
                    "timestamp": event["timestamp"],
                }
            )
            state["updated_at"] = now
            accepted += 1
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


def console_push_snapshot(instance_id: str, *, limit: int = 400) -> dict[str, Any] | None:
    cap = max(1, min(int(limit), RING_LINES))
    with _LOCK:
        state = _BUFFERS.get(str(instance_id or "").strip())
        if not state:
            return None
        agent_id = str(state.get("agent_id") or "")
        seen = _AGENT_SEEN.get(agent_id, 0.0)
        if time.monotonic() - seen > FRESH_SECONDS:
            return None
        lines = list(state["lines"])[-cap:]
        if not lines:
            return None
        return {
            "lines": lines,
            "source": "agent-push",
            "transport": "persistent-http-chunked",
            "agent_id": agent_id,
            "last_seen": state.get("updated_at"),
        }

def _authenticate(headers, backend) -> dict[str, Any]:
    return AgentPairingRepository(backend).authenticate(
        credential_id=str(headers.get("X-Capivara-Agent-Credential") or "").strip(),
        credential_secret=str(headers.get("X-Capivara-Agent-Secret") or "").strip(),
        fingerprint=str(headers.get("X-Capivara-Agent-Fingerprint") or "").strip() or None,
    )


def _read_chunk(stream) -> bytes | None:
    size_line = stream.readline(64)
    if not size_line:
        return None
    raw_size = size_line.strip().split(b";", 1)[0]
    try:
        size = int(raw_size, 16)
    except ValueError as exc:
        raise ValueError("invalid chunk size") from exc
    if size < 0 or size > MAX_FRAME_BYTES:
        raise ValueError("console stream frame too large")
    if size == 0:
        while True:
            trailer = stream.readline(4096)
            if trailer in {b"", b"\r\n", b"\n"}:
                break
        return b""
    payload = stream.read(size)
    if len(payload) != size:
        raise ValueError("short console stream frame")
    ending = stream.read(2)
    if ending != b"\r\n":
        raise ValueError("invalid chunk terminator")
    return payload


def _decode_frame(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid console stream JSON frame") from exc
    if not isinstance(value, dict):
        raise ValueError("console stream frame must be an object")
    return value

def serve_agent_console_stream(handler, *, headers, backend) -> None:
    try:
        identity = _authenticate(headers, backend)
    except AgentCredentialInvalid:
        handler.send_json(401, {"error": "agent_authentication_failed", "message": "Identidade do Agent inválida."})
        return
    transfer = str(headers.get("Transfer-Encoding") or "").strip().lower()
    content_type = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if transfer != "chunked" or content_type != "application/x-ndjson":
        handler.send_json(400, {"error": "invalid_console_stream", "message": "Console stream requires chunked NDJSON."})
        return
    agent_id = str(identity["agent_id"])
    try:
        handler.connection.settimeout(15)
    except OSError:
        pass
    touch_agent(agent_id)
    total_bytes = accepted = duplicates = rejected = frames = 0
    try:
        while True:
            raw = _read_chunk(handler.rfile)
            if raw is None:
                return
            if raw == b"":
                break
            total_bytes += len(raw)
            frames += 1
            if total_bytes > MAX_CONNECTION_BYTES:
                raise ValueError("console stream connection byte limit exceeded")
            frame = _decode_frame(raw)
            kind = str(frame.get("kind") or "").strip().lower()
            if kind == "keepalive":
                touch_agent(agent_id)
                continue
            if kind != "console-batch":
                rejected += 1
                continue
            events = frame.get("events")
            if not isinstance(events, list):
                rejected += 1
                continue
            result = ingest_console_events(agent_id, events, backend=backend)
            accepted += result["accepted"]
            duplicates += result["duplicates"]
            rejected += result["rejected"]
    except (socket.timeout, TimeoutError, BrokenPipeError, ConnectionResetError):
        return
    except ValueError as exc:
        handler.send_json(400, {"error": "invalid_console_stream", "message": str(exc)})
        return
    handler.send_json(
        200,
        {
            "agent_id": agent_id,
            "status": "completed",
            "frames": frames,
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected,
        },
    )


__all__ = [
    "CONSOLE_PUSH_PATH",
    "console_push_snapshot",
    "ingest_console_events",
    "serve_agent_console_stream",
    "touch_agent",
]
