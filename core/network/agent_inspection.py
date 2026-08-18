"""Contract for trustworthy network inspection on Agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentPortInspectionRequest:
    agent_id: str
    node_id: str
    protocol: str
    start_port: int
    end_port: int


@dataclass(frozen=True)
class AgentPortInspectionResponse:
    agent_id: str
    node_id: str
    protocol: str
    occupied_ports: frozenset[int]
    source: str


class AgentPortInspectionTransport(Protocol):
    def inspect_ports(
        self,
        request: AgentPortInspectionRequest,
    ) -> AgentPortInspectionResponse:
        ...


def validate_agent_response(
    request: AgentPortInspectionRequest,
    response: AgentPortInspectionResponse,
) -> set[int]:
    if response.agent_id != request.agent_id:
        raise RuntimeError("Agent inspection identity mismatch")

    if response.node_id != request.node_id:
        raise RuntimeError("Agent inspection node mismatch")

    if response.protocol.lower() != request.protocol.lower():
        raise RuntimeError("Agent inspection protocol mismatch")

    result = {
        int(port)
        for port in response.occupied_ports
        if request.start_port <= int(port) <= request.end_port
    }

    return result
