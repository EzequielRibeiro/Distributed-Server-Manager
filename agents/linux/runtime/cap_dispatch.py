#!/usr/bin/env python3
"""Agent-local cap dispatcher separating read-only CLI from lifecycle mutations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


def _configure_embedded_hybrid_context() -> None:
    """Use the canonical local-Agent paths when runtime is embedded in DSM Hybrid."""
    try:
        dsm_root = RUNTIME_DIR.parents[2]
    except IndexError:
        return

    hybrid_state = dsm_root / "runtime" / "hybrid-agent-state"
    hybrid_config = hybrid_state / "agent.json"
    if not hybrid_config.is_file():
        return

    os.environ.setdefault("CAPIVARA_AGENT_ROOT", str(dsm_root / "agents" / "linux"))
    os.environ.setdefault("CAPIVARA_AGENT_STATE_DIR", str(hybrid_state))
    os.environ.setdefault("CAPIVARA_AGENT_CONFIG", str(hybrid_config))
    os.environ.setdefault("CAPIVARA_AGENT_MODE", "hybrid")
    os.environ.setdefault("CAPIVARA_AGENT_SERVICE", "dsm-dashboard-worker.service")
    os.environ.setdefault("CAPIVARA_DSM_ROOT", str(dsm_root))


# Configure the environment before importing Agent modules because several of
# them resolve CONFIG/STATE paths at import time. Explicit caller overrides win.
_configure_embedded_hybrid_context()

import controller_cli
import local_cli
from instance_runtime import lifecycle

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
LIFECYCLE_ACTIONS = {"start", "stop", "restart"}
_SHELL_VALUE = re.compile(r'^([A-Z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([^#\s]*))\s*$')


def _config() -> dict[str, Any]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except PermissionError as exc:
        raise RuntimeError(
            "Agent operation requires access to the protected Agent identity; use sudo for administrative operations."
        ) from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Agent config is unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Agent config must be a JSON object")
    return value


def _read_shell_values(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _SHELL_VALUE.match(line)
        if not match:
            continue
        result[match.group(1)] = next((value for value in match.groups()[1:] if value is not None), "")
    return result


def _hybrid_doctor() -> dict[str, Any]:
    """Adapt the standalone local Doctor contract to the embedded Hybrid runtime."""
    payload = local_cli._doctor(_config())
    root = Path(os.environ.get("CAPIVARA_DSM_ROOT", RUNTIME_DIR.parents[2]))
    shell = _read_shell_values(root / "config" / "agent.conf")
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    agent_id = str(shell.get("AGENT_ID") or identity.get("agent_id") or "").strip()
    node_id = str(shell.get("DSM_NODE_ID") or identity.get("node_id") or "").strip()
    identity.update(
        {
            "agent_id": agent_id or None,
            "node_id": node_id or None,
            "name": str(shell.get("AGENT_NAME") or identity.get("name") or "").strip() or None,
            "mode": "hybrid",
            "enrollment_mode": "embedded-database",
            "enrolled": bool(agent_id and node_id),
            "credential_type": "embedded-database",
        }
    )
    payload["identity"] = identity
    payload["heartbeat"] = {
        **(payload.get("heartbeat") if isinstance(payload.get("heartbeat"), dict) else {}),
        "controller": {
            "configured": bool(agent_id and node_id),
            "reachable": bool(agent_id and node_id),
            "transport": "embedded-database",
            "error": None if agent_id and node_id else "embedded Hybrid identity is incomplete",
        },
    }
    suppressed = {"not_enrolled", "controller_unreachable"}
    if agent_id and node_id:
        suppressed.add("identity_incomplete")
    service = payload.get("service") if isinstance(payload.get("service"), dict) else {}
    if service.get("healthy"):
        suppressed.add("service_inactive")
    findings = [
        item
        for item in (payload.get("findings") or [])
        if isinstance(item, dict) and str(item.get("code") or "") not in suppressed
    ]
    payload["findings"] = findings
    severities = {str(item.get("severity") or "") for item in findings}
    status = "critical" if "critical" in severities else "degraded" if "warning" in severities else "healthy"
    payload["status"] = status
    payload["ready"] = status != "critical"
    payload["mode"] = "hybrid"
    return payload


def _emit(payload: dict[str, Any], as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}")
        else:
            print(f"{key}: {value}")


def _public_network_request(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    config = _config()
    base = str(config.get("controller_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("controller_url is not configured")
    headers = {
        "Accept": "application/json",
        "X-Capivara-Agent-Credential": str(config.get("credential_id") or ""),
        "X-Capivara-Agent-Secret": str(config.get("credential_secret") or ""),
        "X-Capivara-Agent-Fingerprint": str(config.get("fingerprint") or ""),
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base + "/api/agent/public-network", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", errors="replace") or str(exc)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Controller unavailable: {exc.reason}") from exc


def _public_network_cli(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cap agent network public")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("show")
    commands.add_parser("test")
    setter = commands.add_parser("set")
    setter.add_argument("--hostname", default="")
    setter.add_argument("--ipv4", default="")
    parsed = parser.parse_args(args)
    try:
        if parsed.action == "set":
            result = _public_network_request("POST", {"public_hostname": parsed.hostname, "public_ipv4": parsed.ipv4})
        else:
            result = _public_network_request("GET")
        _emit(result)
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) >= 3 and args[:3] == ["agent", "network", "public"]:
        return _public_network_cli(args[3:])
    if len(args) >= 2 and args[0] == "agent" and args[1] == "controller":
        return controller_cli.main(args[2:])
    if len(args) >= 2 and args[:2] == ["agent", "doctor"] and os.environ.get("CAPIVARA_AGENT_MODE") == "hybrid":
        extra = args[2:]
        if extra not in ([], ["--json"]):
            print("error: unsupported agent doctor option", file=sys.stderr)
            return 2
        try:
            _emit(_hybrid_doctor(), as_json=extra == ["--json"])
            return 0
        except (RuntimeError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
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
