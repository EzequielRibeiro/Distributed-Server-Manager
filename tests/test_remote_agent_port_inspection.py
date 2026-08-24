#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import instance_network
from core.network.port_inspector import PortInspectionError


class FakeRuntimeRepository:
    snapshot_value = None

    def __init__(self, backend):
        self.backend = backend

    def snapshot(self, agent_id, *, refresh_health=True):
        assert refresh_health is True
        value = dict(self.snapshot_value or {})
        assert value.get("agent_id") == agent_id
        return value


def _snapshot(**overrides):
    value = {
        "agent_id": "agent-remote",
        "node_id": "node-remote",
        "health_status": "online",
        "network": {
            "source": "ss",
            "tcp_listen": [8080, 25565],
            "udp_listen": [2302, 2304, 27016],
            "tcp_complete": True,
            "udp_complete": True,
            "complete": True,
        },
    }
    value.update(overrides)
    return value


def _provider(monkeypatch, snapshot=None):
    monkeypatch.delenv("DSM_LOCAL_NODE_ID", raising=False)
    monkeypatch.delenv("DSM_NODE_ID", raising=False)
    FakeRuntimeRepository.snapshot_value = snapshot or _snapshot()
    monkeypatch.setattr(
        instance_network,
        "AgentRuntimeRepository",
        FakeRuntimeRepository,
    )
    return instance_network.occupied_ports_provider_for_backend(object())


def test_controller_uses_remote_agent_inventory(monkeypatch):
    provider = _provider(monkeypatch)

    occupied = provider(
        "agent-remote",
        "node-remote",
        "udp",
        2300,
        2310,
    )

    assert occupied == {2302, 2304}


def test_remote_agent_inventory_fails_closed_when_offline(monkeypatch):
    provider = _provider(
        monkeypatch,
        _snapshot(health_status="offline"),
    )

    with pytest.raises(PortInspectionError, match="stale|not online"):
        provider("agent-remote", "node-remote", "udp", 2300, 2310)


def test_remote_agent_inventory_rejects_node_identity_mismatch(monkeypatch):
    provider = _provider(
        monkeypatch,
        _snapshot(node_id="unexpected-node"),
    )

    with pytest.raises(PortInspectionError, match="node mismatch"):
        provider("agent-remote", "node-remote", "udp", 2300, 2310)


def test_remote_agent_inventory_fails_closed_when_protocol_data_missing(monkeypatch):
    provider = _provider(
        monkeypatch,
        _snapshot(
            network={
                "source": "ss",
                "tcp_listen": [],
                "tcp_complete": True,
                "udp_complete": True,
            }
        ),
    )

    with pytest.raises(PortInspectionError, match="udp port inventory is unavailable"):
        provider("agent-remote", "node-remote", "udp", 2300, 2310)


def test_remote_agent_inventory_rejects_incomplete_protocol(monkeypatch):
    provider = _provider(
        monkeypatch,
        _snapshot(
            network={
                "source": "ss",
                "udp_listen": [],
                "udp_complete": False,
            }
        ),
    )

    with pytest.raises(PortInspectionError, match="udp port inventory is incomplete"):
        provider("agent-remote", "node-remote", "udp", 2300, 2310)


def test_remote_agent_inventory_rejects_missing_completeness_marker(monkeypatch):
    provider = _provider(
        monkeypatch,
        _snapshot(
            network={
                "source": "ss",
                "udp_listen": [],
            }
        ),
    )

    with pytest.raises(PortInspectionError, match="udp port inventory is incomplete"):
        provider("agent-remote", "node-remote", "udp", 2300, 2310)


def test_remote_agent_inventory_accepts_complete_empty_protocol(monkeypatch):
    provider = _provider(
        monkeypatch,
        _snapshot(
            network={
                "source": "ss",
                "udp_listen": [],
                "udp_complete": True,
            }
        ),
    )

    assert provider("agent-remote", "node-remote", "udp", 2300, 2310) == set()


def test_local_node_keeps_direct_os_inspection(monkeypatch):
    monkeypatch.setenv("DSM_LOCAL_NODE_ID", "node-local")
    monkeypatch.delenv("DSM_NODE_ID", raising=False)

    class FailIfConstructed:
        def __init__(self, backend):
            raise AssertionError("remote repository must not be used for local inspection")

    class FakeLocalInspector:
        def occupied(self, protocol, start_port, end_port):
            assert protocol == "tcp"
            assert (start_port, end_port) == (8000, 8100)
            return {8080}

    monkeypatch.setattr(instance_network, "AgentRuntimeRepository", FailIfConstructed)
    monkeypatch.setattr(instance_network, "LocalPortInspector", FakeLocalInspector)

    # Construction itself must remain side-effect-free for the remote repository.
    # The backend object is only consumed if remote placement is actually used.
    original_repository = instance_network.AgentRuntimeRepository

    class LazyRepository:
        def __init__(self, backend):
            self.backend = backend

    monkeypatch.setattr(instance_network, "AgentRuntimeRepository", LazyRepository)
    provider = instance_network.occupied_ports_provider_for_backend(object())
    result = provider("agent-local", "node-local", "tcp", 8000, 8100)

    assert result == {8080}
    assert original_repository is FailIfConstructed
