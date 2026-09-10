#!/usr/bin/env python3
from __future__ import annotations

from core.network_exposure import desired_port_exposure, public_port_exposure


def test_missing_exposure_is_fail_closed() -> None:
    runtime = {
        "network": {
            "ports": [
                {"name": "game", "protocol": "udp", "offset": 0},
                {"name": "rcon", "protocol": "tcp", "offset": 1, "exposure": "private"},
            ]
        }
    }
    ports = {
        "game": {"port": 24010, "protocol": "udp"},
        "rcon": {"port": 24011, "protocol": "tcp"},
    }
    desired = desired_port_exposure(runtime, ports)
    assert desired == [
        {"name": "game", "protocol": "udp", "port": 24010, "exposure": "none"},
        {"name": "rcon", "protocol": "tcp", "port": 24011, "exposure": "private"},
    ]
    assert public_port_exposure(runtime, ports) == []


def test_only_explicit_public_ports_are_selected() -> None:
    runtime = {
        "network": {
            "ports": [
                {"name": "game", "protocol": "udp", "offset": 0, "exposure": "public"},
                {"name": "query", "protocol": "udp", "offset": 1, "exposure": "public"},
                {"name": "rcon", "protocol": "tcp", "offset": 2, "exposure": "none"},
            ]
        }
    }
    ports = {
        "game": {"port": 25000, "protocol": "udp"},
        "query": {"port": 25001, "protocol": "udp"},
        "rcon": {"port": 25002, "protocol": "tcp"},
    }
    assert public_port_exposure(runtime, ports) == [
        {"name": "game", "protocol": "udp", "port": 25000, "exposure": "public"},
        {"name": "query", "protocol": "udp", "port": 25001, "exposure": "public"},
    ]


def test_protocol_mismatch_is_rejected() -> None:
    runtime = {"network": {"ports": [{"name": "game", "protocol": "udp", "offset": 0, "exposure": "public"}]}}
    ports = {"game": {"port": 24010, "protocol": "tcp"}}
    try:
        desired_port_exposure(runtime, ports)
    except ValueError as exc:
        assert "protocol mismatch" in str(exc)
    else:
        raise AssertionError("protocol mismatch should fail")


if __name__ == "__main__":
    test_missing_exposure_is_fail_closed()
    test_only_explicit_public_ports_are_selected()
    test_protocol_mismatch_is_rejected()
    print("network exposure policy: OK")
