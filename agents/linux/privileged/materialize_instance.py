#!/usr/bin/env python3
"""Root-owned helper that applies/removes only validated Capivara instance runtimes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import sys
from typing import Any

INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
RUNTIME_DIR = INSTALL_ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from materializers import resolve_materializer
from runtime_spec import validate_runtime_spec

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
REQUEST_ROOT = STATE_DIR / "privileged-materialization"


def _token(value: Any) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > 191 or any(ch not in allowed for ch in text):
        raise ValueError("invalid instance_id")
    return text


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    try:
        account = pwd.getpwnam("capivara-agent")
        os.chown(temp, account.pw_uid, account.pw_gid)
    except (KeyError, OSError):
        pass
    os.replace(temp, path)


def run(instance_id: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("privileged materializer helper must run as root")
    instance_id = _token(instance_id)
    request_path = REQUEST_ROOT / f"{instance_id}.request.json"
    result_path = REQUEST_ROOT / f"{instance_id}.result.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("kind") != "CapivaraPrivilegedMaterializationRequest":
        raise RuntimeError("invalid privileged materialization request")
    if str(request.get("instance_id") or "") != instance_id:
        raise RuntimeError("privileged materialization instance_id mismatch")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    local_agent_id = str(config.get("agent_id") or "").strip()
    if not local_agent_id:
        raise RuntimeError("local Agent identity is unavailable")
    if str(request.get("agent_id") or "") != local_agent_id:
        raise PermissionError("privileged materialization request belongs to another Agent")
    spec = validate_runtime_spec(request.get("spec"), expected_agent_id=local_agent_id)
    if spec["instance_id"] != instance_id:
        raise RuntimeError("runtime spec instance_id mismatch")
    action = str(request.get("action") or "").strip().lower()
    materializer = resolve_materializer(spec)
    if action == "apply":
        operation = materializer.apply(spec)
    elif action == "remove":
        operation = materializer.remove(spec)
    else:
        raise RuntimeError("unsupported privileged materialization action")
    result = {
        "status": "completed",
        "action": action,
        "instance_id": instance_id,
        "agent_id": local_agent_id,
        "operation": operation,
    }
    _write_result(result_path, result)
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: materialize_instance.py INSTANCE_ID", file=sys.stderr)
        return 2
    instance_id = sys.argv[1]
    result_path = REQUEST_ROOT / f"{_token(instance_id)}.result.json"
    try:
        result = run(instance_id)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        _write_result(
            result_path,
            {"status": "failed", "instance_id": instance_id, "error": str(exc)[:2000]},
        )
        print(f"privileged materialization failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
