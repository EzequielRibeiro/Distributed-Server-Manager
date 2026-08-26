#!/usr/bin/env python3
"""Systemd-backed instance lifecycle adapter with strict unit derivation."""

from __future__ import annotations

import re
import subprocess
from typing import Any, Callable

from .base import AdapterError, InstanceRuntimeAdapter

_INSTANCE_ID = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
Runner = Callable[[list[str], int], tuple[int, str, str]]


def _default_runner(command: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def unit_for_instance(instance: dict[str, Any]) -> str:
    instance_id = str(instance.get("instance_id") or "").strip()
    if not _INSTANCE_ID.fullmatch(instance_id):
        raise AdapterError("invalid instance_id for systemd adapter")
    return f"capivara-instance-{instance_id}.service"


class SystemdAdapter(InstanceRuntimeAdapter):
    name = "systemd"

    def __init__(self, runner: Runner | None = None, *, timeout: int = 30):
        self.runner = runner or _default_runner
        self.timeout = max(1, min(int(timeout), 120))

    def _show(self, instance: dict[str, Any]) -> dict[str, Any]:
        unit = unit_for_instance(instance)
        code, stdout, stderr = self.runner(
            [
                "systemctl",
                "show",
                unit,
                "--property=LoadState",
                "--property=ActiveState",
                "--property=SubState",
                "--no-pager",
            ],
            10,
        )
        values: dict[str, str] = {}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip()
        load_state = values.get("LoadState", "unknown")
        active_state = values.get("ActiveState", "unknown")
        sub_state = values.get("SubState", "unknown")
        return {
            "adapter": self.name,
            "unit": unit,
            "available": code == 0 and load_state not in {"not-found", "error"},
            "load_state": load_state,
            "active_state": active_state,
            "sub_state": sub_state,
            "running": active_state == "active",
            "error": stderr[:2000] or None,
        }

    def status(self, instance: dict[str, Any]) -> dict[str, Any]:
        return self._show(instance)

    def _clear_failed_after_stop(self, unit: str, instance: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """Clear a residual failed state only after an explicit successful stop.

        Some game servers exit non-zero after SIGTERM even though systemd completed
        the requested stop and no process remains.  Keeping that residual failed
        state makes desired=stopped impossible to reconcile.  This normalization is
        intentionally scoped to the explicit stop path so crashes while a runtime is
        expected to be running remain visible as failures.
        """
        if state.get("active_state") != "failed":
            return state
        code, stdout, stderr = self.runner(["systemctl", "reset-failed", unit, "--no-pager"], 10)
        if code != 0:
            detail = (stderr or stdout or "systemctl reset-failed failed")[:2000]
            raise AdapterError(detail)
        return self._show(instance)

    def _lifecycle(self, action: str, instance: dict[str, Any]) -> dict[str, Any]:
        if action not in {"start", "stop", "restart"}:
            raise AdapterError("unsupported systemd lifecycle action")
        before = self._show(instance)
        if not before["available"]:
            raise AdapterError(f"instance systemd unit is unavailable: {before['unit']}")
        if action == "start" and before["running"]:
            return {"action": action, "changed": False, "idempotent": True, "state": before}
        if action == "stop" and not before["running"]:
            if before.get("active_state") == "failed":
                normalized = self._clear_failed_after_stop(str(before["unit"]), instance, before)
                return {"action": action, "changed": True, "idempotent": True, "state": normalized}
            return {"action": action, "changed": False, "idempotent": True, "state": before}
        unit = str(before["unit"])
        code, stdout, stderr = self.runner(["systemctl", action, unit, "--no-pager"], self.timeout)
        if code != 0:
            detail = (stderr or stdout or f"systemctl {action} failed")[:2000]
            raise AdapterError(detail)
        after = self._show(instance)
        if action == "stop":
            after = self._clear_failed_after_stop(unit, instance, after)
        expected_running = action != "stop"
        if not after["available"]:
            raise AdapterError("instance systemd unit became unavailable after lifecycle action")
        if bool(after["running"]) != expected_running:
            raise AdapterError(f"instance did not reach expected state after {action}")
        if action == "stop" and after.get("active_state") == "failed":
            raise AdapterError("instance remained failed after stop normalization")
        return {"action": action, "changed": True, "idempotent": False, "state": after}

    def start(self, instance: dict[str, Any]) -> dict[str, Any]:
        return self._lifecycle("start", instance)

    def stop(self, instance: dict[str, Any]) -> dict[str, Any]:
        return self._lifecycle("stop", instance)

    def restart(self, instance: dict[str, Any]) -> dict[str, Any]:
        return self._lifecycle("restart", instance)

    def doctor(self, instance: dict[str, Any]) -> dict[str, Any]:
        state = self._show(instance)
        findings: list[dict[str, str]] = []
        if not state["available"]:
            findings.append({
                "code": "systemd_unit_unavailable",
                "severity": "critical",
                "message": "The instance systemd unit is not available.",
            })
        elif state["active_state"] == "failed":
            findings.append({
                "code": "systemd_unit_failed",
                "severity": "critical",
                "message": "The instance systemd unit is in failed state.",
            })
        severities = {item["severity"] for item in findings}
        status = "critical" if "critical" in severities else "healthy"
        return {
            "adapter": self.name,
            "status": status,
            "ready": status != "critical",
            "state": state,
            "findings": findings,
        }


__all__ = ["SystemdAdapter", "unit_for_instance"]
