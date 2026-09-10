#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import struct
import time


A2S_INFO = b"\xff\xff\xff\xffTSource Engine Query\x00"


def _cstring(data: bytes, offset: int):
    end = data.find(b"\x00", offset)
    if end < 0:
        raise ValueError("invalid A2S string")
    return data[offset:end].decode("utf-8", errors="replace"), end + 1


def query(host: str, port: int, timeout: float = 3.0) -> dict:
    started = time.monotonic()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(A2S_INFO, (host, port))
        data, _ = sock.recvfrom(65535)

        # Some servers may first return an A2S challenge.
        if data.startswith(b"\xff\xff\xff\xffA") and len(data) >= 9:
            challenge = data[5:9]
            sock.sendto(A2S_INFO + challenge, (host, port))
            data, _ = sock.recvfrom(65535)

    latency_ms = round((time.monotonic() - started) * 1000.0, 2)

    if not data.startswith(b"\xff\xff\xff\xffI"):
        raise ValueError("unexpected A2S_INFO response")

    offset = 5

    if offset >= len(data):
        raise ValueError("truncated A2S_INFO response")

    protocol = data[offset]
    offset += 1

    name, offset = _cstring(data, offset)
    map_name, offset = _cstring(data, offset)
    folder, offset = _cstring(data, offset)
    game, offset = _cstring(data, offset)

    if offset + 5 > len(data):
        raise ValueError("truncated A2S_INFO player fields")

    app_id = struct.unpack_from("<H", data, offset)[0]
    offset += 2

    players = data[offset]
    max_players = data[offset + 1]
    bots = data[offset + 2]

    return {
        "health": "healthy",
        "latency_ms": latency_ms,
        "players_online": players,
        "players_max": max_players,
        "server_name": name,
        "map": map_name,
        "game": game,
        "folder": folder,
        "app_id": app_id,
        "bots": bots,
        "protocol": protocol,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()

    try:
        result = query(args.host, args.port, args.timeout)
    except Exception as exc:
        print(json.dumps({
            "health": "degraded",
            "error": str(exc),
        }))
        return 1

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
