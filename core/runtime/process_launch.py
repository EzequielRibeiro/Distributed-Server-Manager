"""Build the effective launch specification for an instance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .startup_parameters import build_effective_argv


@dataclass(frozen=True)
class ProcessLaunchSpec:
    executable: str
    working_dir: str
    argv: tuple[str, ...]
    environment: dict[str, str]


def _port_environment(
    ports: Mapping[str, int] | None,
) -> dict[str, str]:
    result: dict[str, str] = {}

    for name, port in (ports or {}).items():
        key = (
            "PORT_"
            + re.sub(
                r"[^A-Za-z0-9]+",
                "_",
                str(name),
            ).upper()
        )

        result[key] = str(int(port))

    return result


def build_process_launch_spec(
    definition: Mapping[str, Any],
    *,
    overrides: Mapping[str, Any] | None = None,
    ports: Mapping[str, int] | None = None,
    network_arguments: list[str] | None = None,
    network_environment: Mapping[str, Any] | None = None,
) -> ProcessLaunchSpec:
    process = definition.get("process", {})

    if not isinstance(process, Mapping):
        raise ValueError("process definition must be an object")

    executable = str(process.get("executable", "")).strip()
    working_dir = str(process.get("working_dir", ".")).strip() or "."

    argv = build_effective_argv(
        definition,
        overrides,
    )

    argv.extend(
        str(item)
        for item in (network_arguments or [])
    )

    environment = {
        str(key): str(value)
        for key, value
        in (process.get("environment", {}) or {}).items()
    }

    environment.update(_port_environment(ports))

    environment.update(
        {
            str(key): str(value)
            for key, value
            in (network_environment or {}).items()
        }
    )

    return ProcessLaunchSpec(
        executable=executable,
        working_dir=working_dir,
        argv=tuple(argv),
        environment=environment,
    )
