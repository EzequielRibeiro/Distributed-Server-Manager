#!/usr/bin/env python3
"""Root-owned execution of Agent-local native game commands."""
from __future__ import annotations

import json
import os
import pwd
import sys
from pathlib import Path
from typing import Any


INSTALL_ROOT = Path(
    os.environ.get(
        "CAPIVARA_AGENT_ROOT",
        "/opt/capivara-agent",
    )
)

RUNTIME_DIR = INSTALL_ROOT / "runtime"
COMMON_DIR = INSTALL_ROOT.parent / "common"

for value in (
    RUNTIME_DIR,
    COMMON_DIR,
):
    if str(value) not in sys.path:
        sys.path.insert(
            0,
            str(value),
        )

import instance_runtime
from minecraft_rcon_secret import (
    MinecraftRconSecretError,
    read_password,
)
from source_rcon import (
    SourceRconError,
    execute as execute_source_rcon,
)


STATE_DIR = Path(
    os.environ.get(
        "CAPIVARA_AGENT_STATE_DIR",
        "/var/lib/capivara-agent",
    )
)

CONFIG_PATH = Path(
    os.environ.get(
        "CAPIVARA_AGENT_CONFIG",
        "/etc/capivara-agent/agent.json",
    )
)

REQUEST_ROOT = (
    STATE_DIR
    / "privileged-native-command"
)


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
        raise ValueError(
            f"invalid {label}"
        )
    return text


def _write_result(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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

    result_user = str(
        os.environ.get(
            "CAPIVARA_AGENT_RESULT_USER",
            "capivara-agent",
        )
    ).strip()

    try:
        account = pwd.getpwnam(
            result_user
        )
        os.chown(
            temp,
            account.pw_uid,
            account.pw_gid,
        )
    except (KeyError, OSError):
        pass

    os.replace(
        temp,
        path,
    )


def _minecraft_rcon(
    record: dict[str, Any],
    command: str,
) -> list[str]:
    game_id = str(
        record.get("game_id") or ""
    ).strip().lower()

    environment_id = str(
        record.get("environment_id") or ""
    ).strip().lower()

    if (
        game_id != "minecraft"
        or not environment_id.startswith(
            "minecraft.java."
        )
    ):
        raise RuntimeError(
            "native RCON transport does not "
            "support this game runtime"
        )

    password = read_password(
        record
    )

    rcon = (
        (record.get("ports") or {})
        .get("rcon")
        or {}
    )

    port = int(
        rcon.get("port") or 0
    )

    output = execute_source_rcon(
        "127.0.0.1",
        port,
        password,
        command,
        timeout=5.0,
    )

    return (
        output.splitlines()
        if output
        else []
    )


def run(
    command_id: str,
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError(
            "privileged native command helper "
            "must run as root"
        )

    command_id = _token(
        command_id,
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

    request = json.loads(
        request_path.read_text(
            encoding="utf-8",
        )
    )

    if (
        not isinstance(request, dict)
        or request.get("kind")
        != "CapivaraPrivilegedNativeCommandRequest"
    ):
        raise RuntimeError(
            "invalid privileged native command request"
        )

    if (
        str(request.get("command_id") or "")
        != command_id
    ):
        raise RuntimeError(
            "privileged native command id mismatch"
        )

    config = json.loads(
        CONFIG_PATH.read_text(
            encoding="utf-8",
        )
    )

    local_agent_id = str(
        config.get("agent_id") or ""
    ).strip()

    if not local_agent_id:
        raise RuntimeError(
            "local Agent identity is unavailable"
        )

    if (
        str(request.get("agent_id") or "")
        != local_agent_id
    ):
        raise PermissionError(
            "privileged native command belongs "
            "to another Agent"
        )

    instance_id = _token(
        request.get("instance_id"),
        "instance_id",
    )

    record = instance_runtime.get_instance(
        instance_id
    )

    if not isinstance(
        record,
        dict,
    ):
        raise LookupError(
            "instance not found"
        )

    if (
        str(record.get("agent_id") or "")
        != local_agent_id
    ):
        raise PermissionError(
            "instance belongs to another Agent"
        )

    operation = str(
        request.get("operation") or ""
    ).strip().lower()

    if operation == "console":
        command = str(
            request.get("command") or ""
        ).strip()

        if (
            not command
            or len(command) > 512
            or any(
                value in command
                for value in (
                    "\x00",
                    "\n",
                    "\r",
                )
            )
        ):
            raise ValueError(
                "invalid game console command"
            )

    elif operation == "broadcast":
        message = str(
            request.get("message") or ""
        ).strip()

        if (
            not message
            or len(message) > 1800
            or any(
                value in message
                for value in (
                    "\x00",
                    "\n",
                    "\r",
                )
            )
        ):
            raise ValueError(
                "invalid broadcast message"
            )

        command = (
            f"say {message}"
        )

    elif operation == "save":
        command = (
            "save-all flush"
        )

    else:
        raise ValueError(
            "unsupported privileged "
            "native operation"
        )

    output = _minecraft_rcon(
        record,
        command,
    )

    result = {
        "schema_version": 1,
        "kind": (
            "CapivaraPrivilegedNativeCommandResult"
        ),
        "command_id": command_id,
        "instance_id": instance_id,
        "agent_id": local_agent_id,
        "operation": operation,
        "transport": "minecraft-rcon",
        "status": "completed",
        "output": output,
    }

    _write_result(
        result_path,
        result,
    )

    return result


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: native_command.py COMMAND_ID",
            file=sys.stderr,
        )
        return 2

    command_id = sys.argv[1]

    result_path = (
        REQUEST_ROOT
        / f"{command_id}.result.json"
    )

    try:
        result = run(
            command_id
        )
        print(
            json.dumps(
                result,
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    except (
        MinecraftRconSecretError,
        SourceRconError,
        Exception,
    ) as exc:
        _write_result(
            result_path,
            {
                "status": "failed",
                "command_id": command_id,
                "error": str(exc)[:2000],
            },
        )
        print(
            f"privileged native command failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
