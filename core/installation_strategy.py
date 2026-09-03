"""Canonical installation strategy for Capivara DSM P0-B.

The catalog describes *what* must be acquired and a semantic relative layout.
The Agent resolves that layout below its instance root for the local platform.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from core.runtime_engine_contract import validate_runtime_engine_contract

STRATEGY_VERSION = 1
KIND = "InstallationStrategy"
SUPPORTED_METHODS = {"steamcmd", "download", "copy", "source-build", "custom"}


class InstallationStrategyError(ValueError):
    """Raised when an Installation Strategy is invalid."""


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InstallationStrategyError(f"{field} is required")
    return text


def _relative(value: Any, field: str) -> str:
    text = _text(value, field).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise InstallationStrategyError(f"{field} must be a safe relative path")
    if any(part in {"", "."} for part in path.parts) and text not in {".", ""}:
        raise InstallationStrategyError(f"{field} must be a normalized relative path")
    return "." if text == "." else str(path)


def method_for_provider(provider: str) -> str:
    """Map acquisition provider to installer executor without changing engine identity."""
    value = _text(provider, "artifact.provider").lower()
    if value == "steam":
        return "steamcmd"
    if value in {"http", "http-archive", "github"}:
        return "download"
    if value == "local":
        return "copy"
    if value == "source-build":
        return "source-build"
    if value == "custom":
        return "custom"
    raise InstallationStrategyError(f"unsupported artifact provider: {value}")


def validate_installation_strategy(strategy: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(strategy, Mapping):
        raise InstallationStrategyError("strategy must be an object")
    if strategy.get("strategy_version") != STRATEGY_VERSION:
        raise InstallationStrategyError("unsupported strategy_version")
    if strategy.get("kind") != KIND:
        raise InstallationStrategyError("kind must be InstallationStrategy")

    _text(strategy.get("runtime_id"), "runtime_id")
    _text(strategy.get("engine_id"), "engine_id")

    acquisition = strategy.get("acquisition")
    if not isinstance(acquisition, Mapping):
        raise InstallationStrategyError("acquisition must be an object")
    provider = _text(acquisition.get("provider"), "acquisition.provider").lower()

    installer = strategy.get("installer")
    if not isinstance(installer, Mapping):
        raise InstallationStrategyError("installer must be an object")
    method = _text(installer.get("method"), "installer.method").lower()
    if method not in SUPPORTED_METHODS:
        raise InstallationStrategyError("unsupported installer.method")
    expected = method_for_provider(provider)
    if method != expected:
        raise InstallationStrategyError(
            f"installer.method {method} does not match acquisition provider {provider}"
        )

    layout = strategy.get("layout")
    if not isinstance(layout, Mapping):
        raise InstallationStrategyError("layout must be an object")
    for field in ("working_dir", "artifact_target"):
        _relative(layout.get(field), f"layout.{field}")

    return deepcopy(dict(strategy))


def strategy_from_runtime_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Build P0-B strategy from a validated P0-A Runtime/Engine contract."""
    checked = validate_runtime_engine_contract(contract)
    artifact = checked.get("artifact") or {}
    provider = _text(artifact.get("provider"), "artifact.provider").lower()
    method = method_for_provider(provider)

    artifact_mode = str(checked.get("launch", {}).get("artifact_mode") or "executable").lower()
    target = "server" if artifact_mode == "directory" else "server/runtime"

    strategy = {
        "strategy_version": STRATEGY_VERSION,
        "kind": KIND,
        "runtime_id": checked["runtime"]["id"],
        "engine_id": checked["engine"]["id"],
        "acquisition": deepcopy(dict(artifact)),
        "installer": {
            "method": method,
            "idempotent": True,
        },
        "layout": {
            "working_dir": "server",
            "artifact_target": target,
        },
        "compatibility": {
            "runtime_contract_version": checked["contract_version"],
        },
    }
    return validate_installation_strategy(strategy)


def resolve_agent_layout(
    strategy: Mapping[str, Any], *, instance_root: str, os_name: str
) -> dict[str, str]:
    """Resolve semantic layout to physical paths only at the Agent boundary."""
    checked = validate_installation_strategy(strategy)
    root = _text(instance_root, "instance_root")
    platform = _text(os_name, "os_name").lower()

    if platform == "windows":
        path_cls = PureWindowsPath
    elif platform in {"linux", "darwin", "freebsd"}:
        path_cls = PurePosixPath
    else:
        raise InstallationStrategyError(f"unsupported Agent OS: {platform}")

    root_path = path_cls(root)
    if not root_path.is_absolute():
        raise InstallationStrategyError("instance_root must be absolute at Agent resolution time")

    layout = checked["layout"]
    working = root_path / path_cls(layout["working_dir"])
    target = root_path / path_cls(layout["artifact_target"])
    return {
        "instance_root": str(root_path),
        "working_dir": str(working),
        "artifact_target": str(target),
    }
