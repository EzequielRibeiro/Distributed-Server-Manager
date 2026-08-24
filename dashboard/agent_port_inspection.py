#!/usr/bin/env python3
"""Controller-side remote Agent port inspection backed by fresh heartbeats."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
for path in (ROOT, DATABASE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core.network.agent_inspection import (
    AgentPortInspectionRequest,
    AgentPortInspectionResponse,
)
from agent_runtime_repository import (
    AgentRuntimeNotFound,
    AgentRuntimeRepository,
)


class HeartbeatAgentPortInspectionTransport:
    """Read a fresh, complete socket inventory reported by the selected Agent."""

    def __init__(self, backend) -> None:
        self.repository = AgentRuntimeRepository(backend)

    @staticmethod
    def _ports(network: dict[str, Any], protocol: str) -> frozenset[int]:
        complete_key = f"{protocol}_complete"
        ports_key = f"{protocol}_listen"

        if network.get(complete_key) is not True:
            raise RuntimeError(
                f"Agent {protocol} socket inventory is incomplete"
            )

        raw_ports = network.get(ports_key)
        if not isinstance(raw_ports, list):
            raise RuntimeError(
                f"Agent {protocol} socket inventory is invalid"
            )

        ports: set[int] = set()
        for raw in raw_ports:
            if isinstance(raw, bool):
                raise RuntimeError(
                    f"Agent {protocol} socket inventory is invalid"
                )
            try:
                port = int(raw)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Agent {protocol} socket inventory is invalid"
                ) from exc
            if not 1 <= port <= 65535:
                raise RuntimeError(
                    f"Agent {protocol} socket inventory is invalid"
                )
            ports.add(port)
        return frozenset(ports)

    def inspect_ports(
        self,
        request: AgentPortInspectionRequest,
    ) -> AgentPortInspectionResponse:
        protocol = request.protocol.strip().lower()
        if protocol not in {"tcp", "udp"}:
            raise ValueError(f"unsupported protocol: {protocol}")

        try:
            snapshot = self.repository.snapshot(request.agent_id)
        except AgentRuntimeNotFound as exc:
            raise RuntimeError("Agent runtime inventory is unavailable") from exc

        if str(snapshot.get("agent_id") or "") != request.agent_id:
            raise RuntimeError("Agent inspection identity mismatch")
        if str(snapshot.get("node_id") or "") != request.node_id:
            raise RuntimeError("Agent inspection node mismatch")
        if str(snapshot.get("status") or "").lower() != "active":
            raise RuntimeError("Agent is not active")
        if str(snapshot.get("health_status") or "").lower() != "online":
            raise RuntimeError("Agent heartbeat is not fresh")

        network = snapshot.get("network")
        if not isinstance(network, dict):
            raise RuntimeError("Agent network inventory is unavailable")

        source = str(network.get("source") or "").strip().lower()
        if source not in {"ss", "netstat"}:
            raise RuntimeError("Agent network inventory source is not trusted")

        return AgentPortInspectionResponse(
            agent_id=request.agent_id,
            node_id=request.node_id,
            protocol=protocol,
            occupied_ports=self._ports(network, protocol),
            source=f"heartbeat:{source}",
        )


__all__ = ["HeartbeatAgentPortInspectionTransport"]
