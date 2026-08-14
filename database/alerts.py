#!/usr/bin/env python3
"""Relational alert persistence for Capivara DSM."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

import manager as database


VALID_LEVELS = {"INFO", "WARNING", "CRITICAL"}
VALID_SCOPES = {"controller", "agent", "node", "instance"}
VALID_STATES = {"OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"}
ACTIVE_STATES = {"OPEN", "ACKNOWLEDGED"}


def _validate_level(level: str) -> str:
    level = str(level).strip().upper()
    if level not in VALID_LEVELS:
        raise ValueError(f"invalid alert level: {level}")
    return level


def _validate_scope(scope: str) -> str:
    scope = str(scope).strip().lower()
    if scope not in VALID_SCOPES:
        raise ValueError(f"invalid alert scope: {scope}")
    return scope


def _validate_state(state: str) -> str:
    state = str(state).strip().upper()
    if state not in VALID_STATES:
        raise ValueError(f"invalid alert state: {state}")
    return state


def _validate_limit(limit: int | None) -> int | None:
    if limit is None:
        return None

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("alert query limit must be an integer")

    if limit <= 0:
        raise ValueError("alert query limit must be greater than zero")

    return limit


def _validate_offset(offset: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError("alert query offset must be an integer")

    if offset < 0:
        raise ValueError("alert query offset must be zero or greater")

    return offset


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def _build_query_filters(
    *,
    state: str | None = None,
    level: str | None = None,
    scope: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
    active_only: bool = False,
):
    clauses = []
    parameters = []

    if active_only:
        clauses.append(
            "state IN ('OPEN', 'ACKNOWLEDGED')"
        )
    elif state:
        clauses.append("state=?")
        parameters.append(_validate_state(state))

    if level:
        clauses.append("level=?")
        parameters.append(_validate_level(level))

    if scope:
        clauses.append("scope=?")
        parameters.append(_validate_scope(scope))

    if controller_id:
        clauses.append("controller_id=?")
        parameters.append(controller_id)

    if agent_id:
        clauses.append("agent_id=?")
        parameters.append(agent_id)

    if node_id:
        clauses.append("node_id=?")
        parameters.append(node_id)

    if instance_id:
        clauses.append("instance_id=?")
        parameters.append(instance_id)

    return clauses, parameters

def get_alert(database_path: Path, alert_id: str):
    database.initialize(database_path)

    with closing(database.connect(database_path)) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM alerts
            WHERE id=?
            """,
            (alert_id,),
        ).fetchone()

    return _row_to_dict(row)


def list_alerts(
    database_path: Path,
    *,
    state: str | None = None,
    level: str | None = None,
    scope: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    database.initialize(database_path)

    limit = _validate_limit(limit)
    offset = _validate_offset(offset)

    clauses, parameters = _build_query_filters(
        state=state,
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
    )

    sql = """
        SELECT *
        FROM alerts
    """

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    sql += " ORDER BY opened_at DESC, id"

    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(limit)

        if offset:
            sql += " OFFSET ?"
            parameters.append(offset)
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        parameters.append(offset)

    with closing(database.connect(database_path)) as connection:
        rows = connection.execute(
            sql,
            tuple(parameters),
        ).fetchall()

    return [dict(row) for row in rows]


def list_alerts_page(
    database_path: Path,
    *,
    state: str | None = None,
    level: str | None = None,
    scope: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    limit = _validate_limit(limit)
    offset = _validate_offset(offset)

    items = list_alerts(
        database_path,
        state=state,
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
        limit=limit,
        offset=offset,
    )

    total = count_alerts(
        database_path,
        state=state,
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
    )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

def count_alerts(
    database_path: Path,
    *,
    state: str | None = None,
    level: str | None = None,
    scope: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
):
    database.initialize(database_path)

    clauses, parameters = _build_query_filters(
        state=state,
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
    )

    sql = """
        SELECT COUNT(*) AS total
        FROM alerts
    """

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    with closing(database.connect(database_path)) as connection:
        row = connection.execute(
            sql,
            tuple(parameters),
        ).fetchone()

    return int(row["total"])

def count_active(
    database_path: Path,
    *,
    level: str | None = None,
    scope: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
):
    database.initialize(database_path)

    clauses, parameters = _build_query_filters(
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
        active_only=True,
    )

    sql = """
        SELECT COUNT(*) AS total
        FROM alerts
        WHERE
    """

    sql += " AND ".join(clauses)

    with closing(database.connect(database_path)) as connection:
        row = connection.execute(
            sql,
            tuple(parameters),
        ).fetchone()

    return int(row["total"])

def list_active(
    database_path: Path,
    *,
    level: str | None = None,
    scope: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    database.initialize(database_path)

    limit = _validate_limit(limit)
    offset = _validate_offset(offset)

    clauses, parameters = _build_query_filters(
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
        active_only=True,
    )

    sql = """
        SELECT *
        FROM alerts
        WHERE
    """

    sql += " AND ".join(clauses)

    sql += """
        ORDER BY
            CASE level
                WHEN 'CRITICAL' THEN 0
                WHEN 'WARNING' THEN 1
                ELSE 2
            END,
            opened_at DESC,
            id
    """

    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(limit)

        if offset:
            sql += " OFFSET ?"
            parameters.append(offset)
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        parameters.append(offset)

    with closing(database.connect(database_path)) as connection:
        rows = connection.execute(
            sql,
            tuple(parameters),
        ).fetchall()

    return [dict(row) for row in rows]


def list_active_page(
    database_path: Path,
    *,
    level: str | None = None,
    scope: str | None = None,
    controller_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    limit = _validate_limit(limit)
    offset = _validate_offset(offset)

    items = list_active(
        database_path,
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
        limit=limit,
        offset=offset,
    )

    total = count_active(
        database_path,
        level=level,
        scope=scope,
        controller_id=controller_id,
        agent_id=agent_id,
        node_id=node_id,
        instance_id=instance_id,
    )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

def alert_history(database_path: Path, alert_id: str):
    database.initialize(database_path)

    with closing(database.connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM alert_events
            WHERE alert_id=?
            ORDER BY id
            """,
            (alert_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def _insert_event(
    connection,
    *,
    alert_id: str,
    action: str,
    level: str,
    old_state: str | None,
    new_state: str,
    message: str,
):
    connection.execute(
        """
        INSERT INTO alert_events(
            alert_id,
            action,
            level,
            old_state,
            new_state,
            message
        )
        VALUES (?,?,?,?,?,?)
        """,
        (
            alert_id,
            action,
            level,
            old_state,
            new_state,
            message,
        ),
    )


def open_alert(
    database_path: Path,
    *,
    alert_id: str,
    rule_id: str,
    level: str,
    message: str,
    scope: str,
    controller_id: str,
    agent_id: str | None = None,
    node_id: str | None = None,
    instance_id: str | None = None,
):
    database.initialize(database_path)

    level = _validate_level(level)
    scope = _validate_scope(scope)

    if not alert_id:
        raise ValueError("alert_id is required")

    if not rule_id:
        raise ValueError("rule_id is required")

    if not message:
        raise ValueError("message is required")

    with closing(database.connect(database_path)) as connection:
        with connection:
            current = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

            if current is None:
                connection.execute(
                    """
                    INSERT INTO alerts(
                        id,
                        scope,
                        controller_id,
                        agent_id,
                        node_id,
                        instance_id,
                        rule_id,
                        level,
                        state,
                        message
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        alert_id,
                        scope,
                        controller_id,
                        agent_id,
                        node_id,
                        instance_id,
                        rule_id,
                        level,
                        "OPEN",
                        message,
                    ),
                )

                _insert_event(
                    connection,
                    alert_id=alert_id,
                    action="OPEN",
                    level=level,
                    old_state=None,
                    new_state="OPEN",
                    message=message,
                )

                action = "OPEN"

            elif current["state"] in {"RESOLVED", "SUPPRESSED"}:
                old_state = current["state"]

                connection.execute(
                    """
                    UPDATE alerts
                    SET
                        scope=?,
                        controller_id=?,
                        agent_id=?,
                        node_id=?,
                        instance_id=?,
                        rule_id=?,
                        level=?,
                        state='OPEN',
                        message=?,
                        opened_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        acknowledged_at=NULL,
                        resolved_at=NULL,
                        suppressed_until=NULL
                    WHERE id=?
                    """,
                    (
                        scope,
                        controller_id,
                        agent_id,
                        node_id,
                        instance_id,
                        rule_id,
                        level,
                        message,
                        alert_id,
                    ),
                )

                _insert_event(
                    connection,
                    alert_id=alert_id,
                    action="REOPEN",
                    level=level,
                    old_state=old_state,
                    new_state="OPEN",
                    message=message,
                )

                action = "REOPEN"

            elif level == "CRITICAL" and current["level"] != "CRITICAL":
                old_state = current["state"]

                connection.execute(
                    """
                    UPDATE alerts
                    SET
                        level='CRITICAL',
                        state='OPEN',
                        message=?,
                        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                        acknowledged_at=NULL
                    WHERE id=?
                    """,
                    (
                        message,
                        alert_id,
                    ),
                )

                _insert_event(
                    connection,
                    alert_id=alert_id,
                    action="ESCALATE",
                    level="CRITICAL",
                    old_state=old_state,
                    new_state="OPEN",
                    message=message,
                )

                action = "ESCALATE"

            else:
                action = "UNCHANGED"

            row = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

    result = dict(row)
    result["action"] = action
    return result


def acknowledge_alert(database_path: Path, alert_id: str):
    database.initialize(database_path)

    with closing(database.connect(database_path)) as connection:
        with connection:
            current = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

            if current is None:
                raise ValueError("alert not found")

            if current["state"] != "OPEN":
                raise ValueError("only OPEN alerts can be acknowledged")

            connection.execute(
                """
                UPDATE alerts
                SET
                    state='ACKNOWLEDGED',
                    acknowledged_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=?
                """,
                (alert_id,),
            )

            _insert_event(
                connection,
                alert_id=alert_id,
                action="ACK",
                level=current["level"],
                old_state="OPEN",
                new_state="ACKNOWLEDGED",
                message=current["message"],
            )

            row = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

    return dict(row)


def resolve_alert(database_path: Path, alert_id: str):
    database.initialize(database_path)

    with closing(database.connect(database_path)) as connection:
        with connection:
            current = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

            if current is None:
                return None

            if current["state"] == "RESOLVED":
                return dict(current)

            connection.execute(
                """
                UPDATE alerts
                SET
                    state='RESOLVED',
                    resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    suppressed_until=NULL,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=?
                """,
                (alert_id,),
            )

            _insert_event(
                connection,
                alert_id=alert_id,
                action="RESOLVE",
                level=current["level"],
                old_state=current["state"],
                new_state="RESOLVED",
                message=current["message"],
            )

            row = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

    return dict(row)


def suppress_alert(
    database_path: Path,
    alert_id: str,
    minutes: int,
):
    database.initialize(database_path)

    if minutes <= 0:
        raise ValueError("suppression minutes must be greater than zero")

    with closing(database.connect(database_path)) as connection:
        with connection:
            current = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

            if current is None:
                raise ValueError("alert not found")

            connection.execute(
                """
                UPDATE alerts
                SET
                    state='SUPPRESSED',
                    suppressed_until=strftime(
                        '%Y-%m-%dT%H:%M:%fZ',
                        'now',
                        ?
                    ),
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=?
                """,
                (
                    f"+{minutes} minutes",
                    alert_id,
                ),
            )

            _insert_event(
                connection,
                alert_id=alert_id,
                action="SUPPRESS",
                level=current["level"],
                old_state=current["state"],
                new_state="SUPPRESSED",
                message=current["message"],
            )

            row = connection.execute(
                "SELECT * FROM alerts WHERE id=?",
                (alert_id,),
            ).fetchone()

    return dict(row)
