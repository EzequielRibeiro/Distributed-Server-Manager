#!/usr/bin/env python3
"""M5 maintenance/restart schema for Database Baseline v2."""
from __future__ import annotations

def _types(backend:str)->tuple[str,str,str]:
 b=str(backend or '').strip().lower();ts='TIMESTAMPTZ' if b=='postgresql' else 'TEXT' if b=='sqlite' else 'TIMESTAMP';text='TEXT' if b in {'postgresql','sqlite'} else 'VARCHAR(191)';engine='' if b in {'postgresql','sqlite'} else ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4';return ts,text,engine

def maintenance_ddl(backend:str)->str:
 ts,text,engine=_types(backend)
 return f'''CREATE TABLE instance_maintenance_policy (
 instance_id {text} PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, schedule_mode VARCHAR(32) NOT NULL DEFAULT 'fixed', timezone VARCHAR(128) NOT NULL DEFAULT 'UTC', weekdays_json TEXT NOT NULL,
 start_time VARCHAR(5) NOT NULL DEFAULT '04:00', interval_seconds INTEGER NOT NULL DEFAULT 86400, warning_offsets_json TEXT NOT NULL, warning_template TEXT NOT NULL,
 broadcast_enabled INTEGER NOT NULL DEFAULT 1, coalesce_updates INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1, requested_by {text}, created_at {ts} NOT NULL, updated_at {ts} NOT NULL
){engine};
CREATE TABLE instance_maintenance_state (
 instance_id {text} PRIMARY KEY, next_due_at {ts}, active_run_id {text}, last_started_at {ts}, last_completed_at {ts}, last_error TEXT, updated_at {ts} NOT NULL
){engine};
CREATE TABLE instance_maintenance_runs (
 run_id {text} PRIMARY KEY, instance_id {text} NOT NULL, agent_id {text} NOT NULL, trigger_type VARCHAR(32) NOT NULL DEFAULT 'scheduled', due_at {ts} NOT NULL,
 status VARCHAR(32) NOT NULL, stage VARCHAR(32) NOT NULL, event_json TEXT NOT NULL, warnings_sent_json TEXT NOT NULL, broadcast_ids_json TEXT NOT NULL,
 preflight_command_id {text}, save_command_id {text}, stop_command_id {text}, start_command_id {text}, lifecycle_command_id {text}, readiness_command_id {text},
 error_code VARCHAR(128), error_detail TEXT, created_at {ts} NOT NULL, started_at {ts}, completed_at {ts}, updated_at {ts} NOT NULL
){engine};
CREATE INDEX idx_instance_maintenance_state_due ON instance_maintenance_state(next_due_at,active_run_id);
CREATE INDEX idx_instance_maintenance_runs_instance ON instance_maintenance_runs(instance_id,created_at);'''

def ensure_maintenance_schema(sql:str,backend:str)->str:
 result=sql.rstrip()
 if 'create table instance_maintenance_policy' not in result.lower():result+='\n\n-- M5 maintenance and restart framework\n'+maintenance_ddl(backend)
 return result+'\n'
__all__=['ensure_maintenance_schema','maintenance_ddl']
