"""Durable offline instance relocation and source-port reservation schema."""
from __future__ import annotations


def instance_agent_relocation_ddl(backend: str) -> str:
    name = str(backend).lower()
    if name in {"mysql", "mariadb"}:
        ident, details, timestamp, nullable = "VARCHAR(191)", "LONGTEXT", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP NULL"
        index = "CREATE INDEX"
    elif name == "postgresql":
        ident, details, timestamp, nullable = "TEXT", "TEXT", "TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP", "TIMESTAMPTZ"
        index = "CREATE INDEX IF NOT EXISTS"
    else:
        ident, details, timestamp, nullable = "TEXT", "TEXT", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP", "TEXT"
        index = "CREATE INDEX IF NOT EXISTS"
    return f"""
CREATE TABLE IF NOT EXISTS instance_agent_relocations (
    relocation_id {ident} PRIMARY KEY,
    instance_id {ident} NOT NULL,
    source_agent_id {ident} NOT NULL,
    source_node_id {ident} NOT NULL,
    target_agent_id {ident} NOT NULL,
    target_node_id {ident} NOT NULL,
    source_ports_json {details} NOT NULL,
    target_ports_json {details} NOT NULL,
    source_manifest_path {details},
    source_metadata_json {details},
    target_manifest_path {details},
    source_running INTEGER NOT NULL DEFAULT 0,
    status {ident} NOT NULL DEFAULT 'queued',
    backup_job_id {ident},
    backup_id {ident},
    backup_sha256 {ident},
    export_transfer_id {ident},
    stop_command_id {ident},
    unfence_command_id {ident},
    provisioning_id {ident},
    import_transfer_id {ident},
    imported_backup_id {ident},
    restore_job_id {ident},
    start_command_id {ident},
    rollback_command_id {ident},
    requested_by {ident} NOT NULL,
    last_error {details},
    lease_until BIGINT NOT NULL DEFAULT 0,
    lease_token {ident},
    created_at {timestamp},
    updated_at {timestamp},
    completed_at {nullable},
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (source_agent_id) REFERENCES agents(id),
    FOREIGN KEY (target_agent_id) REFERENCES agents(id)
);
{index} idx_instance_agent_relocations_instance ON instance_agent_relocations(instance_id,status);
{index} idx_instance_agent_relocations_source ON instance_agent_relocations(source_agent_id,status);
{index} idx_instance_agent_relocations_target ON instance_agent_relocations(target_agent_id,status);

CREATE TABLE IF NOT EXISTS instance_agent_relocation_port_holds (
    relocation_id {ident} NOT NULL,
    node_id {ident} NOT NULL,
    protocol VARCHAR(8) NOT NULL,
    port INTEGER NOT NULL,
    PRIMARY KEY (relocation_id,node_id,protocol,port),
    FOREIGN KEY (relocation_id) REFERENCES instance_agent_relocations(relocation_id) ON DELETE CASCADE
);
{index} idx_instance_agent_relocation_holds_node ON instance_agent_relocation_port_holds(node_id,protocol,port);
"""


def ensure_instance_agent_relocation_schema(sql: str, backend: str) -> str:
    if "CREATE TABLE IF NOT EXISTS instance_agent_relocations" in sql:
        return sql
    return sql.rstrip() + "\n" + instance_agent_relocation_ddl(backend) + "\n"


__all__ = ["instance_agent_relocation_ddl", "ensure_instance_agent_relocation_schema"]
