#!/usr/bin/env python3
"""Persistent Agent log ledger schema for Database Baseline v2."""
from __future__ import annotations


def agent_log_event_ddl(backend: str) -> str:
    b = str(backend or "").strip().lower()
    ident = "TEXT" if b in {"postgresql", "sqlite"} else "VARCHAR(191)"
    ts = "TIMESTAMPTZ" if b == "postgresql" else "TEXT" if b == "sqlite" else "VARCHAR(40)"
    engine = "" if b in {"postgresql", "sqlite"} else " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    return f'''CREATE TABLE agent_log_events (
 event_id VARCHAR(64) PRIMARY KEY,
 agent_id {ident} NOT NULL,
 source VARCHAR(64) NOT NULL,
 severity VARCHAR(16) NOT NULL,
 message TEXT NOT NULL,
 line_text TEXT NOT NULL,
 observed_at {ts} NOT NULL,
 ingested_at {ts} NOT NULL,
 instance_id {ident},
 command_id {ident},
 job_id {ident},
 provisioning_id {ident}
){engine};
CREATE INDEX idx_agent_log_events_agent_time ON agent_log_events(agent_id, observed_at);
CREATE INDEX idx_agent_log_events_agent_severity_time ON agent_log_events(agent_id, severity, observed_at);
CREATE INDEX idx_agent_log_events_instance_time ON agent_log_events(instance_id, observed_at);
CREATE INDEX idx_agent_log_events_command ON agent_log_events(command_id);
CREATE INDEX idx_agent_log_events_job ON agent_log_events(job_id);
CREATE INDEX idx_agent_log_events_provisioning ON agent_log_events(provisioning_id);'''


def ensure_agent_log_event_schema(sql: str, backend: str) -> str:
    if "create table agent_log_events" in sql.lower():
        return sql
    return sql.rstrip() + "\n\n" + agent_log_event_ddl(backend) + "\n"


__all__ = ["agent_log_event_ddl", "ensure_agent_log_event_schema"]
