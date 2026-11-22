#!/usr/bin/env python3
"""Fail-closed gate for the startup-only DayZ shutdown message configuration."""
from __future__ import annotations
from typing import Any, Mapping

def require_stopped_instance(view: Mapping[str, Any] | None) -> None:
    """Require an Agent-local runtime observation, not a persisted desired state.

    This check must run under the per-instance lifecycle lock to prevent a
    concurrent DSM start from racing with the messages.xml materialization.
    """
    state = view.get("adapter_state") if isinstance(view, Mapping) else None
    if (
        not isinstance(state, Mapping)
        or state.get("available") is not True
        or str(state.get("active_state") or "").strip().lower() != "inactive"
        or str(view.get("observed_state") or "").strip().lower() != "stopped"
    ):
        raise RuntimeError(
            "DayZ native restart preparation requires a verified stopped instance; "
            "messages.xml is startup-only and no running-process countdown is guaranteed"
        )


def require_prepared_start(
    record: Mapping[str, Any],
    requirement: Mapping[str, Any],
    history: Mapping[str, Any] | None,
) -> None:
    """Ensure the ACK still describes the mission/XML at authorized start.

    Must run inside lifecycle:start lock. This is a configuration check,
    not evidence that the game supports or loaded native shutdown.
    """
    from datetime import datetime, timedelta, timezone
    from xml.etree import ElementTree as ET
    from dayz_messages import MANAGED_TEXT, native_restart_plan

    def utc(value):
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("DayZ native start requires a valid due_at") from exc
        if parsed.tzinfo is None:
            raise RuntimeError("DayZ native start requires a timezone-aware due_at")
        return parsed.astimezone(timezone.utc)

    if not isinstance(requirement, Mapping) or not isinstance(history, Mapping):
        raise RuntimeError("DayZ native start lacks Agent-local preparation history")
    if str(requirement.get("command_id") or "") != str(history.get("command_id") or ""):
        raise RuntimeError("DayZ native start command ID does not match preparation")
    if str(history.get("status") or "") != "completed" or (
        str(history.get("instance_id") or "") != str(record.get("instance_id") or "")
    ):
        raise RuntimeError("DayZ native start has no completed preparation for this instance")
    payload = history.get("result")
    if not isinstance(payload, Mapping) or (
        payload.get("kind") != "CapivaraDayZNativeRestartPrepared"
        or payload.get("materialized") is not True
    ):
        raise RuntimeError("DayZ native start preparation result is incomplete")
    due = utc(requirement.get("due_at"))
    if utc(payload.get("due_at")) != due:
        raise RuntimeError("DayZ native start preparation due_at mismatch")
    current = datetime.now(timezone.utc)
    if due <= current + timedelta(seconds=30) or due > current + timedelta(days=7):
        raise RuntimeError("DayZ native start due_at is expired, imminent or too far away")
    generated = utc(history.get("generated_at"))
    if generated > current + timedelta(seconds=30) or current - generated > timedelta(minutes=5):
        raise RuntimeError("DayZ native start preparation acknowledgement is stale")
    try:
        deadline = int(payload.get("deadline_minutes"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("DayZ native start countdown value is invalid") from exc
    if not (1 <= deadline <= 10080):
        raise RuntimeError("DayZ native start countdown outside allowed limits")
    plan = native_restart_plan(dict(record), deadline)
    if str(plan.mission) != str(payload.get("mission") or ""):
        raise RuntimeError("DayZ native start mission changed after preparation")
    try:
        root = ET.parse(plan.messages_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RuntimeError("DayZ native start messages.xml is unavailable or invalid") from exc
    found = [
        item for item in root.findall("message")
        if str(item.findtext("text") or "").strip() == MANAGED_TEXT
        and str(item.findtext("shutdown") or "").strip() == "1"
        and str(item.findtext("deadline") or "").strip() == str(deadline)
    ]
    if root.tag != "messages" or len(found) != 1:
        raise RuntimeError("DayZ native start messages.xml was changed after preparation")


__all__ = ["require_stopped_instance", "require_prepared_start"]
