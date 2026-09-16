#!/usr/bin/env python3
"""Universal server/content update schema for Database Baseline v2."""
from __future__ import annotations

def _types(backend:str)->tuple[str,str,str]:
 b=str(backend or '').strip().lower()
 ts='TIMESTAMPTZ' if b=='postgresql' else 'TEXT' if b=='sqlite' else 'TIMESTAMP'
 text='TEXT' if b in {'postgresql','sqlite'} else 'VARCHAR(191)'
 engine='' if b in {'postgresql','sqlite'} else ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
 return ts,text,engine

def server_update_ddl(backend:str)->str:
 ts,text,engine=_types(backend)
 return f'''CREATE TABLE instance_update_policy (
 instance_id {text} PRIMARY KEY,
 mode VARCHAR(32) NOT NULL DEFAULT 'manual', timezone VARCHAR(128) NOT NULL DEFAULT 'UTC', weekdays_json TEXT NOT NULL,
 start_time VARCHAR(5) NOT NULL DEFAULT '04:00', duration_minutes INTEGER NOT NULL DEFAULT 60, check_interval_seconds INTEGER NOT NULL DEFAULT 3600,
 backup_before_update INTEGER NOT NULL DEFAULT 1, selection_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, requested_by {text},
 created_at {ts} NOT NULL, updated_at {ts} NOT NULL
){engine};
CREATE TABLE instance_update_state (
 instance_id {text} PRIMARY KEY, agent_id {text} NOT NULL, provider VARCHAR(64) NOT NULL, target_key {text}, installed_version {text}, available_version {text},
 state VARCHAR(32) NOT NULL DEFAULT 'unknown', rollback_supported INTEGER NOT NULL DEFAULT 0, last_checked_at {ts}, last_error_code VARCHAR(128), active_job_id {text}, updated_at {ts} NOT NULL
){engine};
CREATE TABLE instance_update_runs (
 run_id {text} PRIMARY KEY, instance_id {text} NOT NULL, agent_id {text} NOT NULL, game_data_job_id {text}, trigger_type VARCHAR(32) NOT NULL,
 installed_before {text}, target_version {text}, installed_after {text}, status VARCHAR(32) NOT NULL, backup_id {text}, rollback_supported INTEGER NOT NULL DEFAULT 0,
 error_code VARCHAR(128), created_at {ts} NOT NULL, started_at {ts}, completed_at {ts}, updated_at {ts} NOT NULL
){engine};
CREATE INDEX idx_instance_update_state_agent ON instance_update_state(agent_id,state);
CREATE INDEX idx_instance_update_runs_instance ON instance_update_runs(instance_id,created_at);'''

def content_update_ddl(backend:str)->str:
 ts,text,engine=_types(backend)
 return f'''CREATE TABLE content_update_policy (
 instance_id {text} NOT NULL, content_id {text} NOT NULL, mode VARCHAR(32) NOT NULL DEFAULT 'inherit',
 revision INTEGER NOT NULL DEFAULT 1, requested_by {text}, created_at {ts} NOT NULL, updated_at {ts} NOT NULL,
 PRIMARY KEY(instance_id,content_id)
){engine};
CREATE TABLE content_update_state (
 agent_id {text} NOT NULL, instance_id {text} NOT NULL, content_id {text} NOT NULL,
 provider VARCHAR(64) NOT NULL, content_type VARCHAR(64) NOT NULL, package_id {text}, installed_version {text}, available_version {text},
 state VARCHAR(32) NOT NULL DEFAULT 'unknown', detector_supported INTEGER NOT NULL DEFAULT 0, rollback_supported INTEGER NOT NULL DEFAULT 0,
 last_checked_at {ts}, last_error_code VARCHAR(128), last_error TEXT,
 dispatched_available_version {text}, dispatched_assignment_revision INTEGER,
 dispatch_attempted_at {ts}, dispatch_attempted_version {text}, dispatch_attempted_assignment_revision INTEGER, dispatch_error TEXT,
 updated_at {ts} NOT NULL, PRIMARY KEY(agent_id,instance_id,content_id)
){engine};
CREATE INDEX idx_content_update_state_instance ON content_update_state(instance_id,state);
CREATE INDEX idx_content_update_state_agent ON content_update_state(agent_id,state);'''

def ensure_server_update_schema(sql:str,backend:str)->str:
 result=sql.rstrip()
 lowered=result.lower()
 if 'create table instance_update_policy' not in lowered:
  result+='\n\n'+server_update_ddl(backend)
 if 'create table content_update_policy' not in result.lower():
  result+='\n\n-- M4 managed-content update policy and observations\n'+content_update_ddl(backend)
 return result+'\n'

__all__=['content_update_ddl','server_update_ddl','ensure_server_update_schema']
