
"""Network integration between RuntimeDefinition and an instance."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )


from core.network.port_inspector import (
    LocalPortInspector,
    PortInspectionError,
)
from core.network.port_profile import (
    PortProfile,
)


def occupied_ports_for_agent(
    agent_id: str,
    node_id: str,
    protocol: str,
    start_port: int,
    end_port: int,
) -> set[int]:
    """
    Transitional local/hybrid inspector.

    If DSM_LOCAL_NODE_ID is configured, a mismatch fails closed.
    Remote Agent RPC must implement this same contract later.
    """

    local_node = os.environ.get(
        "DSM_LOCAL_NODE_ID",
        "",
    ).strip()

    if not local_node:
        raise PortInspectionError(
            "DSM_LOCAL_NODE_ID is required "
            "for local Agent port inspection"
        )

    if local_node != node_id:
        raise PortInspectionError(
            "remote Agent port inspection "
            "is not available"
        )

    return LocalPortInspector().occupied(
        protocol,
        start_port,
        end_port,
    )


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
