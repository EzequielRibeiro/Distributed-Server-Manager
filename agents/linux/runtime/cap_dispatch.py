#!/usr/bin/env python3
"""Agent-local cap dispatcher separating read-only CLI from lifecycle mutations."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import local_cli
from instance_runtime import lifecycle

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
LIFECYCLE_ACTIONS = {"start", "stop", "restart"}


def _config() -> dict[str, Any]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except PermissionError as exc:
        raise RuntimeError(
            "Agent lifecycle requires access to the protected Agent identity; use sudo for local lifecycle operations."
        ) from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Agent config is unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Agent config must be a JSON object")
    return value


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}")
        else:
            print(f"{key}: {value}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "agent":
        return local_cli.main(args)
    if len(args) >= 3 and args[0] == "instance" and args[1] in LIFECYCLE_ACTIONS:
        action = args[1]
        instance_id = args[2]
        extra = args[3:]
        if extra not in ([], ["--json"]):
            print("error: unsupported instance lifecycle option", file=sys.stderr)
            return 2
        try:
            payload = lifecycle(_config(), instance_id, action)
            _emit(payload, as_json=extra == ["--json"])
            return 0
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except PermissionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        except (RuntimeError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    return local_cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
