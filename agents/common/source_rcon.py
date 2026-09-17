#!/usr/bin/env python3
"""Minimal Source RCON client for Agent-local typed maintenance operations."""

from __future__ import annotations

import socket
import struct


class SourceRconError(RuntimeError):
    pass


_AUTH = 3
_AUTH_RESPONSE = 2
_EXEC = 2
_RESPONSE = 0

_MAX_PACKET = 4096


def _packet(request_id: int, packet_type: int, body: str) -> bytes:
    payload = body.encode("utf-8")
    remainder = struct.pack("<ii", request_id, packet_type) + payload + b"\x00\x00"
    return struct.pack("<i", len(remainder)) + remainder


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()

    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise SourceRconError("RCON connection closed unexpectedly")
        chunks.extend(chunk)

    return bytes(chunks)


def _read_packet(sock: socket.socket) -> tuple[int, int, str]:
    raw_size = _recv_exact(sock, 4)
    (size,) = struct.unpack("<i", raw_size)

    if size < 10 or size > _MAX_PACKET:
        raise SourceRconError("invalid RCON packet size")

    payload = _recv_exact(sock, size)

    request_id, packet_type = struct.unpack("<ii", payload[:8])

    if payload[-2:] != b"\x00\x00":
        raise SourceRconError("invalid RCON packet terminator")

    body = payload[8:-2].decode("utf-8", errors="replace")

    return request_id, packet_type, body


def execute(
    host: str,
    port: int,
    password: str,
    command: str,
    *,
    timeout: float = 5.0,
) -> str:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise SourceRconError("RCON destination must be local")

    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise SourceRconError("invalid RCON port")

    if not password:
        raise SourceRconError("RCON password is unavailable")

    if (
        not command
        or "\x00" in command
        or "\n" in command
        or "\r" in command
        or len(command.encode("utf-8")) > 2048
    ):
        raise SourceRconError("invalid RCON command")

    auth_id = 1001
    command_id = 1002

    try:
        with socket.create_connection(
            (host, port),
            timeout=timeout,
        ) as sock:
            sock.settimeout(timeout)

            sock.sendall(_packet(auth_id, _AUTH, password))

            authenticated = False

            # Some Source RCON implementations emit an empty RESPONSE_VALUE
            # before AUTH_RESPONSE.
            for _ in range(2):
                response_id, response_type, _body = _read_packet(sock)

                if response_id == -1:
                    raise SourceRconError("RCON authentication failed")

                if (
                    response_id == auth_id
                    and response_type == _AUTH_RESPONSE
                ):
                    authenticated = True
                    break

            if not authenticated:
                raise SourceRconError("invalid RCON authentication response")

            sock.sendall(
                _packet(
                    command_id,
                    _EXEC,
                    command,
                )
            )

            response_id, response_type, body = _read_packet(sock)

            if response_id != command_id:
                raise SourceRconError("RCON response id mismatch")

            if response_type not in {_RESPONSE, _AUTH_RESPONSE}:
                raise SourceRconError("unexpected RCON response type")

            return body

    except SourceRconError:
        raise
    except (OSError, socket.timeout) as exc:
        raise SourceRconError(
            "RCON transport failed"
        ) from exc


__all__ = [
    "SourceRconError",
    "execute",
]
