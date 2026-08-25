#!/usr/bin/env python3
"""Database schema extension for Customer Instance Workspace v2.

The workspace schema is appended to the migration-free Baseline v2 for every
supported backend. It stores policy, granular grants, telemetry, console
commands and commercial profile-change state in the database instead of
creating parallel JSON sources of truth.
"""
from __future__ import annotations


def ensure_instance_workspace_schema(sql: str, backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if "CREATE TABLE IF NOT EXISTS instance_workspace_policy" in sql:
        return sql

    if backend in {"mysql", "mariadb"}:
        ident = "VARCHAR(191)"; short = "VARCHAR(128)"; medium = "VARCHAR(512)"
        timestamp = "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"; timestamp_null = "TIMESTAMP NULL"
        json_type = "LONGTEXT"; bigint = "BIGINT"; auto_id = "BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"; index = "CREATE INDEX"
    elif backend == "postgresql":
        ident = "TEXT"; short = "TEXT"; medium = "TEXT"
        timestamp = "TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"; timestamp_null = "TIMESTAMPTZ"
        json_type = "TEXT"; bigint = "BIGINT"; auto_id = "BIGSERIAL PRIMARY KEY"; index = "CREATE INDEX IF NOT EXISTS"
    else:
        ident = "TEXT"; short = "TEXT"; medium = "TEXT"
        timestamp = "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"; timestamp_null = "TEXT"
        json_type = "TEXT"; bigint = "INTEGER"; auto_id = "INTEGER PRIMARY KEY AUTOINCREMENT"; index = "CREATE INDEX IF NOT EXISTS"

    def bool_col(name: str, default: bool = False) -> str:
        if backend == "postgresql": return f"BOOLEAN NOT NULL DEFAULT {'TRUE' if default else 'FALSE'}"
        if backend in {"mysql", "mariadb"}: return f"TINYINT NOT NULL DEFAULT {1 if default else 0}"
        return f"INTEGER NOT NULL DEFAULT {1 if default else 0} CHECK ({name} IN (0,1))"

    ddl = f"""

-- Customer Instance Workspace v2 -------------------------------------------
CREATE TABLE IF NOT EXISTS instance_permission_grants (
    username {ident} NOT NULL,
    instance_id {ident} NOT NULL,
    permission {ident} NOT NULL,
    allowed {bool_col('allowed', True)},
    created_at {timestamp},
    updated_at {timestamp},
    PRIMARY KEY (username, instance_id, permission),
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
{index} idx_instance_permission_grants_instance ON instance_permission_grants(instance_id, username);

CREATE TABLE IF NOT EXISTS instance_workspace_policy (
    instance_id {ident} PRIMARY KEY,
    resource_profile_id {ident},
    cpu_limit_cores DOUBLE PRECISION,
    memory_limit_bytes {bigint},
    storage_limit_bytes {bigint},
    player_limit INTEGER,
    content_mode {short} NOT NULL DEFAULT 'standard',
    mods_allowed {bool_col('mods_allowed')},
    plugins_allowed {bool_col('plugins_allowed')},
    workshop_allowed {bool_col('workshop_allowed')},
    external_upload_allowed {bool_col('external_upload_allowed', True)},
    custom_runtime_allowed {bool_col('custom_runtime_allowed')},
    startup_json {json_type} NOT NULL,
    created_at {timestamp},
    updated_at {timestamp},
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS instance_backup_policy (
    instance_id {ident} PRIMARY KEY,
    enabled {bool_col('enabled', True)},
    schedule_time {short} NOT NULL DEFAULT '04:00',
    healthy_only {bool_col('healthy_only', True)},
    keep_single_operational {bool_col('keep_single_operational', True)},
    updated_at {timestamp},
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contract_change_requests (
    request_id {ident} PRIMARY KEY,
    customer_id {bigint} NOT NULL,
    contract_id {ident} NOT NULL,
    instance_id {ident} NOT NULL,
    current_profile_id {ident},
    requested_profile_id {ident} NOT NULL,
    change_type {short} NOT NULL DEFAULT 'resource_upgrade',
    status {short} NOT NULL DEFAULT 'requested',
    billing_reference {medium},
    requested_by {ident},
    failure_reason {medium},
    requested_at {timestamp},
    approved_at {timestamp_null},
    applied_at {timestamp_null},
    updated_at {timestamp},
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
    FOREIGN KEY (contract_id) REFERENCES service_contracts(id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
{index} idx_contract_change_instance_status ON contract_change_requests(instance_id, status, requested_at);
{index} idx_contract_change_customer_status ON contract_change_requests(customer_id, status, requested_at);

CREATE TABLE IF NOT EXISTS instance_console_commands (
    command_id {ident} PRIMARY KEY,
    agent_id {ident} NOT NULL,
    instance_id {ident} NOT NULL,
    command_text {medium} NOT NULL,
    status {short} NOT NULL DEFAULT 'queued',
    requested_by {ident} NOT NULL,
    result_json {json_type},
    last_error {medium},
    created_at {timestamp},
    delivered_at {timestamp_null},
    completed_at {timestamp_null},
    updated_at {timestamp},
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
{index} idx_instance_console_agent_status ON instance_console_commands(agent_id, status, created_at);
{index} idx_instance_console_instance_created ON instance_console_commands(instance_id, created_at);

CREATE TABLE IF NOT EXISTS instance_console_output (
    id {auto_id},
    instance_id {ident} NOT NULL,
    stream {short} NOT NULL DEFAULT 'console',
    line {medium} NOT NULL,
    created_at {timestamp},
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
{index} idx_instance_console_output_instance ON instance_console_output(instance_id, created_at);

CREATE TABLE IF NOT EXISTS instance_telemetry_samples (
    id {auto_id},
    instance_id {ident} NOT NULL,
    cpu_percent DOUBLE PRECISION,
    memory_bytes {bigint},
    storage_used_bytes {bigint},
    network_rx_bytes {bigint},
    network_tx_bytes {bigint},
    players_online INTEGER,
    players_max INTEGER,
    latency_ms DOUBLE PRECISION,
    uptime_seconds {bigint},
    health {short},
    sampled_at {timestamp},
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
{index} idx_instance_telemetry_instance_sampled ON instance_telemetry_samples(instance_id, sampled_at);
"""
    return sql.rstrip() + ddl + "\n"


__all__ = ["ensure_instance_workspace_schema"]
