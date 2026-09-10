#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
sys.path.insert(0, str(RUNTIME))

import privileged_firewall


def spec():
    return {
        "instance_id": "instance-1",
        "ports": {
            "game": {"port": 24000, "protocol": "udp"},
            "query": {"port": 24003, "protocol": "udp"},
            "rcon": {"port": 24004, "protocol": "tcp"},
        },
        "catalog_runtime_policy": {
            "network_exposure": [
                {"name": "game", "protocol": "udp", "exposure": "public"},
                {"name": "query", "protocol": "udp", "exposure": "public"},
                {"name": "rcon", "protocol": "tcp", "exposure": "none"},
            ],
        },
    }


def test_only_explicit_public_ports_become_firewall_rules():
    assert privileged_firewall.public_rules(spec()) == [
        {"name": "game", "protocol": "udp", "port": 24000},
        {"name": "query", "protocol": "udp", "port": 24003},
    ]


def test_missing_exposure_fails_closed():
    value = spec()
    value["catalog_runtime_policy"]["network_exposure"][0].pop("exposure")
    assert privileged_firewall.public_rules(value) == [
        {"name": "query", "protocol": "udp", "port": 24003},
    ]


def test_protocol_mismatch_is_rejected():
    value = spec()
    value["ports"]["game"]["protocol"] = "tcp"

    try:
        privileged_firewall.public_rules(value)
    except ValueError as exc:
        assert "protocol mismatch" in str(exc)
    else:
        raise AssertionError("protocol mismatch must fail")
