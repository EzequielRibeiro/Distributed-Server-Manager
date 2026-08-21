-- Capivara DSM - Migration 033 - SQLite
-- Universal Configuration Platform.

CREATE TABLE configurations (
    configuration_id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global','agent','instance')),
    scope_key TEXT NOT NULL,
    namespace TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(scope_type, scope_key, namespace)
);

CREATE TABLE configuration_revisions (
    configuration_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(configuration_id, revision)
);

CREATE TABLE agent_configuration_state (
    agent_id TEXT NOT NULL,
    configuration_id TEXT NOT NULL,
    desired_revision INTEGER NOT NULL,
    applied_revision INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    applied_checksum TEXT,
    last_error TEXT,
    reported_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(agent_id, configuration_id),
    FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_configurations_scope_namespace
    ON configurations(scope_type, scope_key, namespace);
CREATE INDEX idx_configuration_revisions_created
    ON configuration_revisions(configuration_id, revision DESC);
CREATE INDEX idx_agent_configuration_state_pending
    ON agent_configuration_state(agent_id, status, desired_revision);
