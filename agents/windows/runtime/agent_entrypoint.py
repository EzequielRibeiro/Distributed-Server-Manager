#!/usr/bin/env python3
"""Windows Agent entrypoint with platform telemetry and typed uninstall lifecycle."""
from __future__ import annotations

import os
import time
from pathlib import Path

import agent
from host_telemetry import collect_host_telemetry
from uninstall_client import (
    accept_command,
    clear_result,
    commit,
    read_result,
    resume_pending_commit,
)

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_DIR = Path(
    os.environ.get(
        "CAPIVARA_AGENT_STATE_DIR",
        PROGRAM_DATA / "CapivaraAgent" / "state",
    )
)
RUNTIME_LOG = STATE_DIR / "agent-runtime.log"


def _runtime_log(message: str, *, error: bool = False) -> None:
    level = "ERROR" if error else "INFO"
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {level} {message}"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if RUNTIME_LOG.exists() and RUNTIME_LOG.stat().st_size > 262144:
            rotated = RUNTIME_LOG.with_name(RUNTIME_LOG.name + ".1")
            try:
                rotated.unlink(missing_ok=True)
            except OSError:
                pass
            RUNTIME_LOG.replace(rotated)
        with RUNTIME_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _recent_logs(limit: int = 200) -> list[str]:
    try:
        return RUNTIME_LOG.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()[-limit:]
    except OSError:
        return []


def _inventory_with_platform_data(config):
    payload = _original_inventory(config)

    try:
        payload["telemetry"] = collect_host_telemetry()
    except Exception as exc:
        _runtime_log(f"host telemetry collection failed: {exc}", error=True)

    payload["agent_logs"] = _recent_logs()

    result = read_result()
    if result:
        payload["uninstall_result"] = result
    return payload


def _heartbeat_with_platform_data(config):
    try:
        result = _original_heartbeat(config)
    except Exception as exc:
        _runtime_log(f"heartbeat failed: {exc}", error=True)
        raise

    _runtime_log(
        "heartbeat ok "
        f"agent={result.get('agent_id')} "
        f"health={result.get('health_status')} "
        f"status={result.get('status')}"
    )

    state = result.get("uninstall_state") if isinstance(result.get("uninstall_state"), dict) else {}
    request_id = str(state.get("request_id") or "").strip()
    status = str(state.get("status") or "").strip().lower()

    # Once the Controller has persisted the prepare acknowledgement, the local
    # acknowledgement file can be cleared before accepting the commit command.
    if request_id and status in {"accepted", "commit-delivered", "committed", "completed", "failed"}:
        clear_result(request_id)

    command = result.get("uninstall_command")
    if not isinstance(command, dict):
        return result

    phase = str(command.get("phase") or "").strip().lower()
    if phase == "prepare":
        report = accept_command(command)
        message = (
            f"uninstall request={report.get('request_id')} "
            f"phase=prepare status={report.get('status')}"
        )
        _runtime_log(message)
        print(message, flush=True)
        return result

    if phase == "commit":
        report = commit(str(command.get("request_id") or ""))
        message = (
            f"uninstall request={report.get('request_id')} "
            f"phase=commit status={report.get('status')}"
        )
        _runtime_log(message)
        print(message, flush=True)
        # The detached PowerShell process waits briefly before removing the
        # Scheduled Task/runtime. Exit now so files are no longer held open.
        raise SystemExit(0)

    raise RuntimeError("unsupported uninstall command phase")


_original_inventory = agent._inventory
_original_heartbeat = agent.heartbeat
agent._inventory = _inventory_with_platform_data
agent.heartbeat = _heartbeat_with_platform_data


if __name__ == "__main__":
    # Recover the narrow crash window in which "committed" was persisted but
    # the detached PowerShell process never actually received control.
    if resume_pending_commit():
        raise SystemExit(0)
    agent.run_forever()
