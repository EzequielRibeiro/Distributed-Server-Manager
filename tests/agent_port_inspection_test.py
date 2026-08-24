#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core.network.agent_inspection import (
    AgentPortInspectionResponse,
)
from core.network.port_inspector import (
    PortInspectionError,
    RemoteAgentPortInspector,
)
from dashboard.agent_port_inspection import (
    HeartbeatAgentPortInspectionTransport,
)


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.request = None

    def inspect_ports(self, request):
        self.request = request
        return self.response


class FakeRuntimeRepository:
    def __init__(self, snapshot):
        self.value = snapshot

    def snapshot(self, agent_id):
        return dict(self.value)


class RemoteAgentPortInspectorTest(unittest.TestCase):
    def test_remote_inspector_validates_identity_and_filters_range(self):
        transport = FakeTransport(
            AgentPortInspectionResponse(
                agent_id="agent-1",
                node_id="node-1",
                protocol="udp",
                occupied_ports=frozenset({2299, 2302, 2305, 9999}),
                source="heartbeat:ss",
            )
        )
        inspector = RemoteAgentPortInspector(
            agent_id="agent-1",
            node_id="node-1",
            transport=transport,
        )

        self.assertEqual(inspector.occupied("udp", 2300, 2305), {2302, 2305})
        self.assertEqual(transport.request.agent_id, "agent-1")
        self.assertEqual(transport.request.node_id, "node-1")

    def test_remote_inspector_fails_closed_on_identity_mismatch(self):
        transport = FakeTransport(
            AgentPortInspectionResponse(
                agent_id="other-agent",
                node_id="node-1",
                protocol="udp",
                occupied_ports=frozenset(),
                source="heartbeat:ss",
            )
        )
        inspector = RemoteAgentPortInspector(
            agent_id="agent-1",
            node_id="node-1",
            transport=transport,
        )
        with self.assertRaises(PortInspectionError):
            inspector.occupied("udp", 2300, 2400)


class HeartbeatTransportTest(unittest.TestCase):
    @staticmethod
    def transport(snapshot):
        transport = HeartbeatAgentPortInspectionTransport.__new__(
            HeartbeatAgentPortInspectionTransport
        )
        transport.repository = FakeRuntimeRepository(snapshot)
        return transport

    @staticmethod
    def request():
        from core.network.agent_inspection import AgentPortInspectionRequest

        return AgentPortInspectionRequest(
            agent_id="agent-1",
            node_id="node-1",
            protocol="udp",
            start_port=2300,
            end_port=2400,
        )

    def snapshot(self, **updates):
        value = {
            "agent_id": "agent-1",
            "node_id": "node-1",
            "status": "active",
            "health_status": "online",
            "network": {
                "source": "ss",
                "tcp_listen": [22, 8080],
                "udp_listen": [2302, 2305, 27016],
                "tcp_complete": True,
                "udp_complete": True,
                "complete": True,
            },
        }
        value.update(updates)
        return value

    def test_complete_online_inventory_is_returned(self):
        response = self.transport(self.snapshot()).inspect_ports(self.request())
        self.assertEqual(response.occupied_ports, frozenset({2302, 2305, 27016}))
        self.assertEqual(response.source, "heartbeat:ss")

    def test_stale_agent_fails_closed(self):
        transport = self.transport(self.snapshot(health_status="degraded"))
        with self.assertRaisesRegex(RuntimeError, "heartbeat is not fresh"):
            transport.inspect_ports(self.request())

    def test_incomplete_inventory_fails_closed(self):
        snapshot = self.snapshot()
        snapshot["network"]["udp_complete"] = False
        transport = self.transport(snapshot)
        with self.assertRaisesRegex(RuntimeError, "inventory is incomplete"):
            transport.inspect_ports(self.request())

    def test_malformed_inventory_fails_closed(self):
        snapshot = self.snapshot()
        snapshot["network"]["udp_listen"] = [2302, "not-a-port"]
        transport = self.transport(snapshot)
        with self.assertRaisesRegex(RuntimeError, "inventory is invalid"):
            transport.inspect_ports(self.request())

    def test_untrusted_inventory_source_fails_closed(self):
        snapshot = self.snapshot()
        snapshot["network"]["source"] = "unknown"
        transport = self.transport(snapshot)
        with self.assertRaisesRegex(RuntimeError, "source is not trusted"):
            transport.inspect_ports(self.request())


if __name__ == "__main__":
    unittest.main()
