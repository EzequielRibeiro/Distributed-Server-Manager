"""Resolve declared game/mod/plugin configuration files."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .manifest import ConfigurationManifest


class ConfigurationDiscoveryError(RuntimeError):
    pass


def serverfiles_root(instance_path: Path) -> Path:
    return (Path(instance_path) / "serverfiles").resolve()


def resolve_configuration_path(
    instance_path: Path,
    relative_path: str,
) -> Path:
    root = serverfiles_root(instance_path)
    target = (root / relative_path).resolve()

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ConfigurationDiscoveryError(
            "configuration path escapes serverfiles"
        ) from exc

    if target.is_symlink():
        raise ConfigurationDiscoveryError(
            "symbolic-link configuration files are not allowed"
        )

    return target


def discover_configurations(
    instance_path: Path,
    definition: Mapping[str, Any],
) -> list[dict[str, Any]]:
    manifest = ConfigurationManifest.from_runtime_definition(
        definition
    )

    result: list[dict[str, Any]] = []

    for entry in manifest.entries:
        target = resolve_configuration_path(
            Path(instance_path),
            entry.path,
        )

        exists = target.is_file()

        if not exists and not entry.optional:
            state = "missing"
        elif not exists:
            state = "optional-missing"
        else:
            state = "available"

        item = asdict(entry)
        item.update(
            {
                "exists": exists,
                "state": state,
                "size": (
                    target.stat().st_size
                    if exists
                    else 0
                ),
            }
        )

        result.append(item)

    return result
