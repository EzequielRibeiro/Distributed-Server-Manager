"""Operating-system network port inspection."""

from __future__ import annotations

import re
import subprocess

from core.network.agent_inspection import (
    AgentPortInspectionRequest,
    AgentPortInspectionTransport,
    validate_agent_response,
)


class PortInspectionError(RuntimeError):
    pass


class LocalPortInspector:
    """Inspect ports on the Controller/local Agent host."""

    def occupied(
        self,
        protocol: str,
        start_port: int,
        end_port: int,
    ) -> set[int]:
        protocol = protocol.strip().lower()

        if protocol == "udp":
            command = ["ss", "-H", "-lun"]
        elif protocol == "tcp":
            command = ["ss", "-H", "-ltn"]
        else:
            raise ValueError(f"unsupported protocol: {protocol}")

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PortInspectionError(
                "unable to inspect operating-system ports"
            ) from exc

        if result.returncode != 0:
            raise PortInspectionError(
                "unable to inspect operating-system ports"
            )

        ports: set[int] = set()
        for line in result.stdout.splitlines():
            for field in line.split():
                match = re.search(r":([0-9]+)$", field)
                if not match:
                    continue
                port = int(match.group(1))
                if start_port <= port <= end_port:
                    ports.add(port)
                    break
        return ports


class RemoteAgentPortInspector:
    """Inspect ports reported by a specific remote Agent transport."""

    def __init__(
        self,
        *,
        agent_id: str,
        node_id: str,
        transport: AgentPortInspectionTransport,
    ) -> None:
        self.agent_id = str(agent_id).strip()
        self.node_id = str(node_id).strip()
        self.transport = transport
        if not self.agent_id or not self.node_id:
            raise ValueError("agent_id and node_id are required")

    def occupied(
        self,
        protocol: str,
        start_port: int,
        end_port: int,
    ) -> set[int]:
        protocol = protocol.strip().lower()
        if protocol not in {"tcp", "udp"}:
            raise ValueError(f"unsupported protocol: {protocol}")
        if not (1 <= int(start_port) <= int(end_port) <= 65535):
            raise ValueError("invalid port inspection range")

        request = AgentPortInspectionRequest(
            agent_id=self.agent_id,
            node_id=self.node_id,
            protocol=protocol,
            start_port=int(start_port),
            end_port=int(end_port),
        )
        try:
            response = self.transport.inspect_ports(request)
            return validate_agent_response(request, response)
        except PortInspectionError:
            raise
        except Exception as exc:
            raise PortInspectionError(
                "unable to inspect remote Agent ports"
            ) from exc
