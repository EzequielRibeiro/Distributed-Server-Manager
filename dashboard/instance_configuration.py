"""Instance configuration surface used by Dashboard APIs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.configuration.discovery import (
    discover_configurations,
    resolve_configuration_path,
)


MAX_CONFIGURATION_FILE = 2 * 1024 * 1024


def list_instance_configurations(
    instance_path: Path,
    definition: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return only files explicitly declared as configuration."""

    return discover_configurations(
        Path(instance_path),
        definition,
    )


def read_instance_configuration(
    instance_path: Path,
    definition: Mapping[str, Any],
    configuration_id: str,
) -> dict[str, Any]:
    items = list_instance_configurations(
        instance_path,
        definition,
    )

    selected = next(
        (
            item
            for item in items
            if item["id"] == configuration_id
        ),
        None,
    )

    if selected is None:
        raise ValueError("configuration is not declared")

    if not selected["exists"]:
        raise FileNotFoundError(selected["path"])

    path = resolve_configuration_path(
        Path(instance_path),
        selected["path"],
    )

    if path.stat().st_size > MAX_CONFIGURATION_FILE:
        raise ValueError("configuration file is too large")

    return {
        **selected,
        "content": path.read_text(
            encoding="utf-8",
            errors="replace",
        ),
    }


def write_instance_configuration(
    instance_path: Path,
    definition: Mapping[str, Any],
    configuration_id: str,
    content: str,
) -> dict[str, Any]:
    items = list_instance_configurations(
        instance_path,
        definition,
    )

    selected = next(
        (
            item
            for item in items
            if item["id"] == configuration_id
        ),
        None,
    )

    if selected is None:
        raise ValueError("configuration is not declared")

    if not selected["editable"]:
        raise PermissionError(
            "configuration is read-only"
        )

    encoded = str(content).encode("utf-8")

    if len(encoded) > MAX_CONFIGURATION_FILE:
        raise ValueError("configuration file is too large")

    path = resolve_configuration_path(
        Path(instance_path),
        selected["path"],
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)

    return {
        **selected,
        "exists": True,
        "state": "available",
        "size": len(encoded),
    }
