#!/usr/bin/env python3
"""Canonical alert-event action constraint helpers.

The raw vendor baselines are historical inputs. This module keeps the compiled
Baseline v2 contract aligned with runtime alert actions and provides the DDL
fragments used by versioned upgrades.
"""
from __future__ import annotations

import re


ALERT_EVENT_ACTIONS = (
    "OPEN",
    "REOPEN",
    "ESCALATE",
    "ACK",
    "RESOLVE",
    "SUPPRESS",
    "NOTE",
)

_ACTION_LIST_PATTERN = re.compile(
    r"(action\s+IN\s*\(\s*"
    r"'OPEN'\s*,\s*"
    r"'REOPEN'\s*,\s*"
    r"'ESCALATE'\s*,\s*"
    r"'ACK'\s*,\s*"
    r"'RESOLVE'\s*,\s*"
    r"'SUPPRESS')"
    r"(\s*\))",
    re.IGNORECASE,
)


def ensure_alert_event_note_schema(sql: str, backend: str) -> str:
    """Ensure the compiled alert_events action CHECK accepts NOTE.

    Baseline compilation already uses post-processors for schema extensions.
    Keeping this transformation here avoids mutating historical migration input
    while making every newly compiled SQLite/PostgreSQL/MySQL/MariaDB baseline
    expose the runtime action contract.
    """
    if "create table alert_events" not in sql.lower():
        raise ValueError("alert_events table is missing from database baseline")

    match = _ACTION_LIST_PATTERN.search(sql)
    if not match:
        # If NOTE is already part of the canonical action list, no rewrite is
        # needed. Otherwise fail loudly instead of silently shipping drift.
        table_pos = sql.lower().find("create table alert_events")
        note_pos = sql.lower().find("'note'", table_pos)
        if note_pos >= 0:
            return sql
        raise ValueError(f"alert_events action CHECK not recognized for backend: {backend}")

    return sql[: match.start()] + match.group(1) + ",\n                'NOTE'" + match.group(2) + sql[match.end() :]


def action_check_expression(column: str = "action") -> str:
    values = ",".join(f"'{value}'" for value in ALERT_EVENT_ACTIONS)
    return f"{column} IN ({values})"


__all__ = [
    "ALERT_EVENT_ACTIONS",
    "action_check_expression",
    "ensure_alert_event_note_schema",
]
