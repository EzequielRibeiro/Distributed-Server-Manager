
"""Network integration between RuntimeDefinition and an instance."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

for module_dir in (ROOT, DATABASE_DIR):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))


from core.network.agent_inspection import (
    AgentPortInspectionRequest,
    AgentPortInspectionResponse,
    validate_agent_response,
)
from core.network.port_inspector import (
    LocalPortInspector,
    PortInspectionError,
)
from core.network.port_profile import (
    PortProfile,
)
from agent_runtime_repository import (
    AgentRuntimeNotFound,
    AgentRuntimeRepository,
)


OccupiedPortsProvider = Callable[[str, str, str, int, int], set[int]]


def occupied_ports_for_agent(
    agent_id: str,
    node_id: str,
    protocol: str,
    start_port: int,
    end_port: int,
) -> set[int]:
    """Inspect ports on the local Agent/hybrid host.

    This compatibility entry point remains intentionally local. Controller
    callers that already have a database backend must use
    :func:`occupied_ports_provider_for_backend` so remote Agent inventory can
    be inspected without pretending the Controller is the selected Agent.
    """

    local_node = (
        os.environ.get("DSM_LOCAL_NODE_ID", "").strip()
        or os.environ.get("DSM_NODE_ID", "").strip()
    )

    if not local_node:
        raise PortInspectionError(
            "DSM_LOCAL_NODE_ID is required "
            "for local Agent port inspection"
        )

    if local_node != node_id:
        raise PortInspectionError(
            "remote Agent port inspection "
            "requires a backend-aware provider"
        )

    return LocalPortInspector().occupied(
        protocol,
        start_port,
        end_port,
    )


def _remote_inventory_response(
    repository: AgentRuntimeRepository,
    request: AgentPortInspectionRequest,
) -> AgentPortInspectionResponse:
    """Build a trustworthy inspection response from the latest heartbeat.

    Agents publish the output of ``network_inventory.collect_network_inventory``
    with every heartbeat.  The Controller only accepts an online Agent, a
    matching Agent/node identity and a protocol inventory with a known source.
    Missing or malformed data fails closed rather than being interpreted as an
    empty host.
    """

    try:
        snapshot = repository.snapshot(
            request.agent_id,
            refresh_health=True,
        )
    except AgentRuntimeNotFound as exc:
        raise PortInspectionError(
            f"Agent runtime inventory not found: {request.agent_id}"
        ) from exc
    except Exception as exc:
        raise PortInspectionError(
            "Agent runtime inventory could not be read"
        ) from exc

    if str(snapshot.get("health_status") or "").lower() != "online":
        raise PortInspectionError(
            "remote Agent port inventory is stale or Agent is not online"
        )

    network = snapshot.get("network")
    if not isinstance(network, Mapping):
        raise PortInspectionError(
            "remote Agent network inventory is unavailable"
        )

    source = str(network.get("source") or "").strip()
    if not source:
        raise PortInspectionError(
            "remote Agent network inventory has no source"
        )

    protocol = request.protocol.lower()
    key = {
        "tcp": "tcp_listen",
        "udp": "udp_listen",
    }.get(protocol)
    if key is None:
        raise PortInspectionError(
            f"unsupported port inspection protocol: {request.protocol}"
        )

    raw_ports = network.get(key)
    if not isinstance(raw_ports, list):
        raise PortInspectionError(
            f"remote Agent {protocol} port inventory is unavailable"
        )

    ports: set[int] = set()
    try:
        for value in raw_ports:
            port = int(value)
            if not 1 <= port <= 65535:
                raise ValueError
            ports.add(port)
    except (TypeError, ValueError) as exc:
        raise PortInspectionError(
            f"remote Agent {protocol} port inventory is malformed"
        ) from exc

    response = AgentPortInspectionResponse(
        agent_id=str(snapshot.get("agent_id") or ""),
        node_id=str(snapshot.get("node_id") or ""),
        protocol=protocol,
        occupied_ports=frozenset(ports),
        source=f"agent_runtime_inventory:{source}",
    )

    try:
        validate_agent_response(request, response)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise PortInspectionError(str(exc)) from exc

    return response


def occupied_ports_provider_for_backend(backend) -> OccupiedPortsProvider:
    """Return a port provider suitable for Controller, Agent or hybrid roles.

    Local/hybrid placement retains direct operating-system inspection.  When
    the selected node is remote (or this process is a pure Controller with no
    local node identity), the Controller consumes the selected Agent's latest
    persisted network inventory from the configured database backend.
    """

    repository = AgentRuntimeRepository(backend)

    def occupied(
        agent_id: str,
        node_id: str,
        protocol: str,
        start_port: int,
        end_port: int,
    ) -> set[int]:
        local_node = (
            os.environ.get("DSM_LOCAL_NODE_ID", "").strip()
            or os.environ.get("DSM_NODE_ID", "").strip()
        )

        if local_node and local_node == node_id:
            return LocalPortInspector().occupied(
                protocol,
                start_port,
                end_port,
            )

        request = AgentPortInspectionRequest(
            agent_id=str(agent_id),
            node_id=str(node_id),
            protocol=str(protocol).lower(),
            start_port=int(start_port),
            end_port=int(end_port),
        )
        response = _remote_inventory_response(repository, request)

        try:
            return validate_agent_response(request, response)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise PortInspectionError(str(exc)) from exc

    return occupied


def _format_template(
    template: str,
    ports: Mapping[str, int],
) -> str:
    try:
        return template.format(
            **ports
        )
    except KeyError as exc:
        raise ValueError(
            "network application references "
            f"unknown port: {exc.args[0]}"
        ) from exc


def _property_path(
    instance_path: Path,
    relative: str,
) -> Path:
    relative_path = Path(
        relative
    )

    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise ValueError(
            "invalid network property file"
        )

    serverfiles = (
        instance_path
        / "serverfiles"
    ).resolve()

    target = (
        serverfiles
        / relative_path
    ).resolve()

    try:
        target.relative_to(
            serverfiles
        )
    except ValueError as exc:
        raise ValueError(
            "network property file escapes "
            "instance serverfiles"
        ) from exc

    if target.is_symlink():
        raise ValueError(
            "network property file cannot "
            "be a symbolic link"
        )

    return target


def _write_property(
    path: Path,
    key: str,
    value: str,
) -> None:
    text = (
        path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        if path.exists()
        else ""
    )

    pattern = re.compile(
        rf"(?m)^{re.escape(key)}=.*$"
    )

    line = (
        f"{key}={value}"
    )

    if pattern.search(text):
        text = pattern.sub(
            line,
            text,
            count=1,
        )
    else:
        if (
            text
            and not text.endswith("\n")
        ):
            text += "\n"

        text += (
            line
            + "\n"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )


def apply_instance_network(
    instance_path: Path,
    definition: Mapping[str, Any],
    reservations: Mapping[str, int],
) -> dict[str, Any]:
    profile = PortProfile.from_mapping(
        definition.get(
            "network"
        )
    )

    if profile is None:
        return {
            "arguments": [],
            "environment": {},
        }

    missing = (
        profile.names
        - set(
            reservations
        )
    )

    if missing:
        raise RuntimeError(
            "instance network reservations "
            "are incomplete: "
            + ", ".join(
                sorted(missing)
            )
        )

    arguments: list[str] = []

    for application in profile.applications:
        if application.kind == "argument":
            arguments.append(
                _format_template(
                    application.template
                    or "",
                    reservations,
                )
            )

        elif application.kind == "property":
            path = _property_path(
                Path(instance_path),
                application.file
                or "",
            )

            value = _format_template(
                application.value
                or "",
                reservations,
            )

            _write_property(
                path,
                application.key
                or "",
                value,
            )

    environment = {
        (
            "PORT_"
            + re.sub(
                r"[^A-Za-z0-9]+",
                "_",
                name,
            ).upper()
        ): int(port)
        for name, port
        in reservations.items()
    }

    return {
        "arguments": arguments,
        "environment": environment,
    }
