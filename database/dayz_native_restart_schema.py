#!/usr/bin/env python3
"""M6 DayZ native restart command schema for Database Baseline v2."""
from __future__ import annotations


def _types(backend: str) -> tuple[str, str, str]:
    name = str(backend or "").strip().lower()
    timestamp = "TIMESTAMPTZ" if name == "postgresql" else "TEXT" if name == "sqlite" else "TIMESTAMP"
    text = "TEXT" if name in {"postgresql", "sqlite"} else "VARCHAR(191)"
    engine = "" if name in {"postgresql", "sqlite"} else " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    return timestamp, text, engine


def dayz_native_restart_ddl(backend: str) -> str:
    timestamp, text, engine = _types(backend)
    return f'''CREATE TABLE dayz_native_restart_commands (
 command_id {text} PRIMARY KEY,
 agent_id {text} NOT NULL,
 instance_id {text} NOT NULL,
 due_at {timestamp} NOT NULL,
 status VARCHAR(32) NOT NULL,
 requested_by {text},
 result_json TEXT,
 last_error TEXT,
 created_at {timestamp} NOT NULL,
 delivered_at {timestamp},
 completed_at {timestamp},
 updated_at {timestamp} NOT NULL
){engine};
CREATE INDEX idx_dayz_native_restart_agent_status ON dayz_native_restart_commands(agent_id,status,created_at);
CREATE INDEX idx_dayz_native_restart_instance_status ON dayz_native_restart_commands(instance_id,status,created_at);'''


def ensure_dayz_native_restart_schema(sql: str, backend: str) -> str:
    result = sql.rstrip()
    if "create table dayz_native_restart_commands" not in result.lower():
        result += "\n\n-- M6 DayZ native restart commands\n" + dayz_native_restart_ddl(backend)
    return result + "\n"


__all__ = ["dayz_native_restart_ddl", "ensure_dayz_native_restart_schema"]
