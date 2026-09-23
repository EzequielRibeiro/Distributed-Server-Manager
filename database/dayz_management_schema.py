#!/usr/bin/env python3
"""DayZ map/wipe operation queue for Database Baseline v2."""
from __future__ import annotations

def _types(backend: str):
    name=str(backend or "").strip().lower()
    ts="TIMESTAMPTZ" if name=="postgresql" else "TEXT" if name=="sqlite" else "TIMESTAMP"
    text="TEXT" if name in {"postgresql","sqlite"} else "VARCHAR(191)"
    longtext="TEXT" if name in {"postgresql","sqlite"} else "LONGTEXT"
    engine="" if name in {"postgresql","sqlite"} else " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    return ts,text,longtext,engine

def dayz_management_ddl(backend: str) -> str:
    ts,text,longtext,engine=_types(backend)
    return f'''CREATE TABLE dayz_operations (
 operation_id {text} PRIMARY KEY,
 agent_id {text} NOT NULL,
 instance_id {text} NOT NULL,
 action VARCHAR(32) NOT NULL,
 status VARCHAR(32) NOT NULL,
 requested_by {text},
 scheduled_at {ts} NOT NULL,
 payload_json {longtext} NOT NULL,
 result_json {longtext},
 last_error {longtext},
 created_at {ts} NOT NULL,
 delivered_at {ts},
 completed_at {ts},
 canceled_at {ts},
 updated_at {ts} NOT NULL
){engine};
CREATE INDEX idx_dayz_operations_agent_due ON dayz_operations(agent_id,status,scheduled_at,created_at);
CREATE INDEX idx_dayz_operations_instance_created ON dayz_operations(instance_id,created_at);'''

def ensure_dayz_management_schema(sql: str, backend: str) -> str:
    result=sql.rstrip()
    if "create table dayz_operations" not in result.lower():
        result+="\n\n-- DayZ map and wipe operations\n"+dayz_management_ddl(backend)
    return result+"\n"

__all__=["dayz_management_ddl","ensure_dayz_management_schema"]
