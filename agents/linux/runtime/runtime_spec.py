#!/usr/bin/env python3
"""Validated Agent-local specification used to materialize instance runtimes."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
VALID_DESIRED_STATES = {"running", "stopped"}


class RuntimeSpecError(ValueError):
    pass


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise RuntimeSpecError(f"invalid {label}")
    return text


def _absolute(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or not os.path.isabs(text) or "\x00" in text or "\n" in text or "\r" in text:
        raise RuntimeSpecError(f"invalid {label}")
    return str(Path(text))


def _absolute_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 128:
        raise RuntimeSpecError(f"invalid {label}")
    return [_absolute(item, label) for item in value]


def validate_runtime_spec(spec: dict[str, Any], *, expected_agent_id: str | None = None) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise RuntimeSpecError("runtime spec must be an object")
    result = dict(spec)
    result["schema_version"] = 1
    result["kind"] = "CapivaraInstanceRuntimeSpec"
    result["instance_id"] = _token(result.get("instance_id"), "instance_id")
    result["agent_id"] = _token(result.get("agent_id"), "agent_id")
    if expected_agent_id is not None and result["agent_id"] != _token(expected_agent_id, "expected_agent_id"):
        raise RuntimeSpecError("runtime spec belongs to another Agent")
    if result.get("storage_pool_id") is not None:
        result["storage_pool_id"] = _token(result.get("storage_pool_id"), "storage_pool_id")
    result["runtime_id"] = _token(result.get("runtime_id") or result["instance_id"], "runtime_id")
    result["adapter"] = _token(result.get("adapter") or "systemd", "adapter").lower()
    if result["adapter"] != "systemd":
        raise RuntimeSpecError("unsupported runtime materialization adapter")
    result["working_directory"] = _absolute(result.get("working_directory") or result.get("path"), "working_directory")
    result["executable"] = _absolute(result.get("executable"), "executable")
    arguments = result.get("arguments", [])
    if not isinstance(arguments, list) or len(arguments) > 128:
        raise RuntimeSpecError("invalid arguments")
    normalized_arguments: list[str] = []
    for item in arguments:
        value = str(item)
        if "\x00" in value or "\n" in value or "\r" in value or len(value) > 4096:
            raise RuntimeSpecError("invalid runtime argument")
        normalized_arguments.append(value)
    result["arguments"] = normalized_arguments
    environment = result.get("environment", {})
    if not isinstance(environment, dict) or len(environment) > 128:
        raise RuntimeSpecError("invalid environment")
    normalized_environment: dict[str, str] = {}
    for key, value in environment.items():
        name = str(key)
        text = str(value)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) or "\x00" in text or "\n" in text or "\r" in text:
            raise RuntimeSpecError("invalid environment entry")
        normalized_environment[name] = text
    result["environment"] = normalized_environment
    user = str(result.get("user") or "capivara-instance").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", user):
        raise RuntimeSpecError("invalid runtime user")
    result["user"] = user
    desired = str(result.get("desired_state") or "stopped").strip().lower()
    if desired not in VALID_DESIRED_STATES:
        raise RuntimeSpecError("invalid desired_state")
    result["desired_state"] = desired

    if result.get("instance_state_root") is not None:
        result["instance_state_root"] = _absolute(result["instance_state_root"], "instance_state_root")
    if result.get("configuration_root") is not None:
        result["configuration_root"] = _absolute(result["configuration_root"], "configuration_root")
    if result.get("config_path") is not None:
        result["config_path"] = _absolute(result["config_path"], "config_path")
    result["writable_directories"] = _absolute_list(result.get("writable_directories"), "writable_directories")

    seed_files = result.get("seed_files") or []
    if not isinstance(seed_files, list) or len(seed_files) > 128:
        raise RuntimeSpecError("invalid seed_files")
    result["seed_files"] = [
        {"source": _absolute(item.get("source"), "seed source"), "target": _absolute(item.get("target"), "seed target")}
        for item in seed_files
        if isinstance(item, dict)
    ]
    if len(result["seed_files"]) != len(seed_files):
        raise RuntimeSpecError("invalid seed_files")

    bind_paths = result.get("bind_paths") or []
    if not isinstance(bind_paths, list) or len(bind_paths) > 128:
        raise RuntimeSpecError("invalid bind_paths")
    result["bind_paths"] = [
        {"source": _absolute(item.get("source"), "bind source"), "target": _absolute(item.get("target"), "bind target")}
        for item in bind_paths
        if isinstance(item, dict)
    ]
    if len(result["bind_paths"]) != len(bind_paths):
        raise RuntimeSpecError("invalid bind_paths")

    result["path"] = result["working_directory"]
    return result


__all__ = ["RuntimeSpecError", "VALID_DESIRED_STATES", "validate_runtime_spec"]
