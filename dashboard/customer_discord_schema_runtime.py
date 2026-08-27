#!/usr/bin/env python3
"""Runtime reconciliation for the additive customer Discord schema."""
from __future__ import annotations

from alert_repository import AlertSession, dialect_for_backend
from discord_integration_schema import discord_integration_ddl


def _table_exists(backend, session) -> bool:
    ph = dialect_for_backend(backend).placeholder
    name = str(backend.name).lower()
    if name == "sqlite":
        row = session.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name={ph}",
            ("customer_discord_connections",),
        ).fetchone()
    else:
        row = session.execute(
            f"SELECT table_name FROM information_schema.tables WHERE table_schema="
            + ("current_schema()" if name == "postgresql" else "DATABASE()")
            + f" AND table_name={ph}",
            ("customer_discord_connections",),
        ).fetchone()
    return row is not None


def ensure_customer_discord_schema(legacy) -> None:
    backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
    backend.initialize()
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            if _table_exists(backend, session):
                return
            statements = [statement.strip() for statement in discord_integration_ddl(backend.name).split(";") if statement.strip()]
            for statement in statements:
                session.execute(statement)
            connection.commit()
        finally:
            session.close()


__all__ = ["ensure_customer_discord_schema"]
