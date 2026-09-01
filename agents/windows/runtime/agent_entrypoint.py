#!/usr/bin/env python3
"""Windows Agent entrypoint with typed remote-uninstall lifecycle integration."""
from __future__ import annotations

import agent
from uninstall_client import (
    accept_command,
    clear_result,
    commit,
    read_result,
    resume_pending_commit,
)


def _inventory_with_uninstall(config):
    payload = _original_inventory(config)
    result = read_result()
    if result:
        payload["uninstall_result"] = result
    return payload


def _heartbeat_with_uninstall(config):
    result = _original_heartbeat(config)
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
        print(
            f"uninstall request={report.get('request_id')} phase=prepare status={report.get('status')}",
            flush=True,
        )
        return result

    if phase == "commit":
        report = commit(str(command.get("request_id") or ""))
        print(
            f"uninstall request={report.get('request_id')} phase=commit status={report.get('status')}",
            flush=True,
        )
        # The detached PowerShell process waits briefly before removing the
        # Scheduled Task/runtime. Exit now so files are no longer held open.
        raise SystemExit(0)

    raise RuntimeError("unsupported uninstall command phase")


_original_inventory = agent._inventory
_original_heartbeat = agent.heartbeat
agent._inventory = _inventory_with_uninstall
agent.heartbeat = _heartbeat_with_uninstall


if __name__ == "__main__":
    # Recover the narrow crash window in which "committed" was persisted but
    # the detached PowerShell process never actually received control.
    if resume_pending_commit():
        raise SystemExit(0)
    agent.run_forever()
