#!/usr/bin/env python3
"""Bridge Agent-native commands to the privileged Hybrid helper."""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any


STATE_DIR = Path(
    os.environ.get(
        "CAPIVARA_AGENT_STATE_DIR",
        "/var/lib/capivara-agent",
    )
)
REQUEST_ROOT = STATE_DIR / "privileged-native-command"


def _token(
    value: Any,
    label: str,
    max_length: int = 191,
) -> str:
    text = str(value or "").strip()
    allowed = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789._-"
    )
    if (
        not text
        or len(text) > max_length
        or any(ch not in allowed for ch in text)
    ):
        raise ValueError(f"invalid {label}")
    return text


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )
    temp.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def execute(
    instance: dict[str, Any],
    operation: str,
    *,
    command: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    instance_id = _token(
        instance.get("instance_id"),
        "instance_id",
    )
    agent_id = _token(
        instance.get("agent_id"),
        "agent_id",
    )

    operation = str(operation or "").strip().lower()
    if operation not in {
        "console",
        "broadcast",
        "save",
    }:
        raise ValueError(
            "unsupported privileged native operation"
        )

    command_id = _token(
        f"native-{uuid.uuid4().hex}",
        "command_id",
    )

    request_path = (
        REQUEST_ROOT
        / f"{command_id}.request.json"
    )
    result_path = (
        REQUEST_ROOT
        / f"{command_id}.result.json"
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": (
            "CapivaraPrivilegedNativeCommandRequest"
        ),
        "command_id": command_id,
        "instance_id": instance_id,
        "agent_id": agent_id,
        "operation": operation,
    }

    if operation == "console":
        payload["command"] = str(command or "")
    elif operation == "broadcast":
        payload["message"] = str(message or "")

    try:
        result_path.unlink()
    except FileNotFoundError:
        pass

    _atomic_json(
        request_path,
        payload,
    )

    template = os.environ.get(
        "CAPIVARA_NATIVE_COMMAND_UNIT_TEMPLATE",
        "capivara-agent-native-command@{command_id}.service",
    )

    unit = template.format(
        command_id=command_id,
    )

    completed = subprocess.run(
        [
            "systemctl",
            "start",
            unit,
            "--no-pager",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    if completed.returncode != 0:
        detail = (
            completed.stderr
            or completed.stdout
            or "privileged native command helper failed"
        )
        raise RuntimeError(
            str(detail)[:2000]
        )

    try:
        result = json.loads(
            result_path.read_text(
                encoding="utf-8",
            )
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "privileged native command returned "
            f"no valid result: {exc}"
        ) from exc

    if (
        not isinstance(result, dict)
        or result.get("status") != "completed"
    ):
        raise RuntimeError(
            str(
                (result or {}).get("error")
                or "privileged native command failed"
            )[:2000]
        )

    return result


__all__ = ["execute"]
