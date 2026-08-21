"""Windows Service Control Manager adapter for game-agnostic instance lifecycle."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from .base import AdapterError, InstanceRuntimeAdapter

_SERVICE = re.compile(r"^[A-Za-z0-9_.-]{1,256}$")


def _service_name(instance: dict[str, Any]) -> str:
    value = str(instance.get("runtime_id") or "").strip()
    if not _SERVICE.fullmatch(value):
        raise AdapterError("instance runtime_id must be a valid Windows service name")
    return value


def _run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(
            ["sc.exe", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError(f"Windows service operation failed: {exc}") from exc


def _query(service: str) -> dict[str, Any]:
    result = _run("query", service)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        return {
            "available": False,
            "active_state": "unknown",
            "service": service,
            "returncode": result.returncode,
            "detail": output.strip()[:2000],
        }
    state = "unknown"
    match = re.search(r"STATE\s*:\s*\d+\s+(\w+)", output, re.IGNORECASE)
    if match:
        token = match.group(1).upper()
        state = {
            "RUNNING": "active",
            "STOPPED": "inactive",
            "START_PENDING": "activating",
            "STOP_PENDING": "deactivating",
            "PAUSED": "inactive",
        }.get(token, token.lower())
    return {"available": True, "active_state": state, "service": service}


class WindowsServiceAdapter(InstanceRuntimeAdapter):
    name = "windows-service"

    def status(self, instance: dict[str, Any]) -> dict[str, Any]:
        return _query(_service_name(instance))

    def _change(self, instance: dict[str, Any], action: str) -> dict[str, Any]:
        service = _service_name(instance)
        command = "start" if action == "start" else "stop"
        result = _run(command, service)
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        # sc.exe returns non-zero when the service is already in the requested state.
        state = _query(service)
        expected = "active" if action == "start" else "inactive"
        if result.returncode != 0 and state.get("active_state") != expected:
            raise AdapterError(f"failed to {action} Windows service {service}: {output[:2000]}")
        return {"action": action, "service": service, "returncode": result.returncode, "state": state}

    def start(self, instance: dict[str, Any]) -> dict[str, Any]:
        return self._change(instance, "start")

    def stop(self, instance: dict[str, Any]) -> dict[str, Any]:
        return self._change(instance, "stop")

    def restart(self, instance: dict[str, Any]) -> dict[str, Any]:
        service = _service_name(instance)
        before = _query(service)
        if before.get("available") and before.get("active_state") != "inactive":
            self._change(instance, "stop")
        started = self._change(instance, "start")
        return {"action": "restart", "service": service, "before": before, "state": started["state"]}

    def doctor(self, instance: dict[str, Any]) -> dict[str, Any]:
        state = self.status(instance)
        findings: list[dict[str, str]] = []
        if not state.get("available"):
            findings.append({
                "code": "windows_service_unavailable",
                "severity": "critical",
                "message": f"Windows service {state.get('service')} is not available.",
            })
        return {
            "adapter": self.name,
            "ready": not findings,
            "state": state,
            "findings": findings,
        }


__all__ = ["WindowsServiceAdapter"]
