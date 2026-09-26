#!/usr/bin/env python3
"""Credential-free Minecraft Java status ping, scoped by callers to loopback.

Never request or retain the sample player names/UUIDs from the status response.
"""
from __future__ import annotations

import json
import socket
import struct
import time
from typing import Any

_MAX_PACKET = 1024 * 1024


def _varint(number: int) -> bytes:
    result = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        result.append(byte | (0x80 if number else 0))
        if not number:
            return bytes(result)


def _read_exact(connection: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise EOFError("Minecraft status response ended unexpectedly")
        result.extend(chunk)
    return bytes(result)


def _read_varint(connection: socket.socket) -> int:
    value = 0
    for shift in range(0, 35, 7):
        byte = _read_exact(connection, 1)[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
    raise ValueError("Minecraft status varint too long")


def query_java_status(port: Any, timeout_seconds: Any = 2) -> dict[str, Any]:
    """Ask the local Java gameplay listener for online/max players.

    A failed or disabled status endpoint returns unknown ({}), never zero.
    Port comes solely from the Agent's reserved TCP game binding.
    """
    try:
        port = int(port)
        timeout = max(1, min(float(timeout_seconds), 5))
    except (TypeError, ValueError, OverflowError):
        return {}
    if not 1 <= port <= 65535:
        return {}

    started = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            name = b"localhost"
            # Status handshake: packet 0, protocol 0, hostname, reserved port,
            # state 1. Protocol 0 is accepted for status even across versions.
            handshake = (
                _varint(0) + _varint(0) + _varint(len(name)) + name
                + struct.pack(">H", port) + _varint(1)
            )
            conn.sendall(_varint(len(handshake)) + handshake + b"\x01\x00")
            length = _read_varint(conn)
            if length < 3 or length > _MAX_PACKET:
                return {}
            packet_id = _read_varint(conn)
            if packet_id != 0:
                return {}
            # JSON length is bounded separately; reading an exact JSON payload
            # also works if an endpoint appends unexpected extra packet bytes.
            json_size = _read_varint(conn)
            if json_size <= 0 or json_size > length or json_size > _MAX_PACKET:
                return {}
            payload = json.loads(_read_exact(conn, json_size).decode("utf-8"))
            players = payload.get("players") if isinstance(payload, dict) else None
            if not isinstance(players, dict):
                return {}
            online = players.get("online")
            maximum = players.get("max")
            if (
                isinstance(online, bool) or isinstance(maximum, bool)
                or not isinstance(online, int) or not isinstance(maximum, int)
                or online < 0 or maximum < 0
            ):
                return {}
            return {
                "players_online": online,
                "players_max": maximum,
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            }
    except (OSError, TimeoutError, EOFError, ValueError, UnicodeError, json.JSONDecodeError):
        return {}


def query_reserved_java_game_port(record: dict, telemetry_config: dict) -> dict[str, Any]:
    ports = record.get("ports")
    if not isinstance(ports, dict):
        return {}
    binding = ports.get("game")
    if not isinstance(binding, dict) or str(binding.get("protocol") or "").lower() != "tcp":
        return {}
    return query_java_status(
        binding.get("port"),
        telemetry_config.get("query_timeout_seconds") or 2,
    )
