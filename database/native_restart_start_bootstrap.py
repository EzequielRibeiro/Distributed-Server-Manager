#!/usr/bin/env python3
"""Defer an authorized DayZ start until its startup-only countdown is prepared.

This is Controller-side ordering, not proof of game-side countdown or shutdown.
The Agent must independently verify stopped state before materializing XML.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

def _utc(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _fail_queued_start(repository, command, reason):
    """Record dispatch failure without projecting a new game runtime state."""
    ph = repository.dialect.placeholder
    with repository.session(transaction=True) as session:
        session.execute(
            f"UPDATE agent_instance_commands SET status='failed', last_error={ph}, "
            f"completed_at={ph}, updated_at={ph} WHERE command_id={ph} "
            "AND instance_id=" + ph + " AND status='queued' AND action='start'",
            (
                str(reason)[:2000],
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                str(command["command_id"]), str(command["instance_id"]),
            ),
        )


def authorize_dispatch(repository, command, *, now=None):
    """Return True only if start can safely be sent to the owning Agent.

    Only governs new, queued user/admin start requests. MaintenanceWorker's
    existing checked preparation/start sequence remains authoritative.
    """
    if str(command.get("action") or "") != "start":
        return True
    if str(command.get("status") or "") != "queued":
        return True
    if str(command.get("requested_by") or "") == "maintenance-worker":
        return True

    ph = repository.dialect.placeholder
    with repository.session() as session:
        row = session.execute(
            "SELECT i.game_id, p.enabled, s.next_due_at FROM instances i "
            "LEFT JOIN instance_maintenance_policy p ON p.instance_id=i.id "
            "LEFT JOIN instance_maintenance_state s ON s.instance_id=i.id "
            f"WHERE i.id={ph} AND i.agent_id={ph}",
            (str(command["instance_id"]), str(command["agent_id"])),
        ).fetchone()
    if row is None:
        _fail_queued_start(repository, command, "Instance/Agent binding is no longer valid")
        return False
    if str(row["game_id"] or "").lower() != "dayz" or not bool(row["enabled"]):
        return True

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        due = _utc(row["next_due_at"])
    except (ValueError, TypeError):
        _fail_queued_start(repository, command, "DayZ maintenance schedule has no valid next due time")
        return False
    # Bootstrap a future startup window, never a stale or imminent countdown.
    if due <= current + timedelta(minutes=2) or due > current + timedelta(days=7):
        _fail_queued_start(
            repository, command,
            "DayZ native maintenance start bootstrap requires a window "
            "more than 2 minutes away and within 7 days; update schedule first",
        )
        return False

    from dayz_native_restart_repository import DayZNativeRestartRepository, DayZNativeRestartCommandConflict
    native = DayZNativeRestartRepository(repository.backend)
    prepared = native.for_instance_due(str(command["instance_id"]), due)
    start_created = _utc(command["created_at"])

    # An old XML preparation does not automatically survive a new stop/start.
    if prepared is not None:
        status = str(prepared.get("status") or "").lower()
        prepare_created = _utc(prepared["created_at"])
        if prepare_created >= start_created:
            if status == "completed" and prepared.get("completed_at"):
                return _utc(prepared["completed_at"]) >= start_created
            if status in {"queued", "delivered"}:
                return False
            if status == "failed":
                _fail_queued_start(
                    repository, command,
                    "DayZ native maintenance preparation failed: "
                    + str(prepared.get("last_error") or "see Agent result"),
                )
                return False
            _fail_queued_start(repository, command, "Unrecognized DayZ native preparation state")
            return False
    try:
        native.enqueue(
            agent_id=str(command["agent_id"]),
            instance_id=str(command["instance_id"]),
            due_at=due,
            requested_by="instance-start-bootstrap",
        )
    except (DayZNativeRestartCommandConflict, ValueError, PermissionError) as exc:
        _fail_queued_start(repository, command, "DayZ native start bootstrap blocked: " + str(exc))
    return False


__all__ = ["authorize_dispatch"]
