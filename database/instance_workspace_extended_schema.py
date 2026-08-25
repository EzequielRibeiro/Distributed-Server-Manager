#!/usr/bin/env python3
"""Additional Database Baseline v2 objects for Customer Instance Workspace."""
from __future__ import annotations


def ensure_instance_workspace_extended_schema(sql: str, backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if "CREATE TABLE IF NOT EXISTS instance_file_commands" in sql:
        return sql

    if backend in {"mysql", "mariadb"}:
        ident="VARCHAR(191)";short="VARCHAR(128)";medium="VARCHAR(1024)";json_type="LONGTEXT";bigint="BIGINT";timestamp="TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP";timestamp_null="TIMESTAMP NULL";index="CREATE INDEX"
    elif backend == "postgresql":
        ident="TEXT";short="TEXT";medium="TEXT";json_type="TEXT";bigint="BIGINT";timestamp="TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP";timestamp_null="TIMESTAMPTZ";index="CREATE INDEX IF NOT EXISTS"
    else:
        ident="TEXT";short="TEXT";medium="TEXT";json_type="TEXT";bigint="INTEGER";timestamp="TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP";timestamp_null="TEXT";index="CREATE INDEX IF NOT EXISTS"

    ddl=f"""

-- Customer Instance Workspace v2: distributed files/resources, upgrade history and deleted backup vault
CREATE TABLE IF NOT EXISTS instance_file_commands (
    command_id {ident} PRIMARY KEY,
    agent_id {ident} NOT NULL,
    instance_id {ident} NOT NULL,
    action {short} NOT NULL,
    path {medium},
    target_path {medium},
    payload_json {json_type},
    policy_json {json_type},
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
{index} idx_instance_file_agent_status ON instance_file_commands(agent_id,status,created_at);
{index} idx_instance_file_instance_created ON instance_file_commands(instance_id,created_at);

CREATE TABLE IF NOT EXISTS instance_resource_commands (
    command_id {ident} PRIMARY KEY,
    agent_id {ident} NOT NULL,
    instance_id {ident} NOT NULL,
    resource_profile_id {ident} NOT NULL,
    resources_json {json_type} NOT NULL,
    status {short} NOT NULL DEFAULT 'queued',
    requested_by {ident},
    result_json {json_type},
    last_error {medium},
    created_at {timestamp},
    delivered_at {timestamp_null},
    completed_at {timestamp_null},
    updated_at {timestamp},
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
{index} idx_instance_resource_agent_status ON instance_resource_commands(agent_id,status,created_at);
{index} idx_instance_resource_instance_created ON instance_resource_commands(instance_id,created_at);

CREATE TABLE IF NOT EXISTS service_contract_revisions (
    revision_id {ident} PRIMARY KEY,
    contract_id {ident} NOT NULL,
    instance_id {ident},
    revision_number INTEGER NOT NULL,
    resource_profile_id {ident},
    resources_json {json_type} NOT NULL,
    entitlements_json {json_type} NOT NULL,
    reason {short} NOT NULL,
    billing_reference {medium},
    effective_from {timestamp},
    effective_until {timestamp_null},
    created_by {ident},
    created_at {timestamp},
    UNIQUE (contract_id, revision_number),
    FOREIGN KEY (contract_id) REFERENCES service_contracts(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE SET NULL
);
{index} idx_contract_revisions_contract ON service_contract_revisions(contract_id,revision_number);
{index} idx_contract_revisions_instance ON service_contract_revisions(instance_id,effective_from);

CREATE TABLE IF NOT EXISTS deleted_instance_backups (
    vault_id {ident} PRIMARY KEY,
    customer_id {bigint} NOT NULL,
    source_instance_id {ident} NOT NULL,
    source_instance_name {medium},
    game_id {ident} NOT NULL,
    runtime_id {ident},
    backup_id {ident},
    artifact_path {medium} NOT NULL,
    size_bytes {bigint},
    sha256 {short},
    manifest_json {json_type},
    created_at {timestamp},
    expires_at {timestamp_null},
    deleted_at {timestamp_null},
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
{index} idx_deleted_instance_backups_customer_expiry ON deleted_instance_backups(customer_id,expires_at);
{index} idx_deleted_instance_backups_source ON deleted_instance_backups(source_instance_id,created_at);
"""
    return sql.rstrip()+ddl+"\n"


__all__=["ensure_instance_workspace_extended_schema"]
