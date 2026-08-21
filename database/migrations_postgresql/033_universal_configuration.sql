-- Capivara DSM - Migration 033 - PostgreSQL
CREATE TABLE configurations (
    configuration_id VARCHAR(191) PRIMARY KEY,
    scope_type VARCHAR(32) NOT NULL CHECK (scope_type IN ('global','agent','instance')),
    scope_key VARCHAR(191) NOT NULL,
    namespace VARCHAR(128) NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    updated_by VARCHAR(191),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE(scope_type, scope_key, namespace)
);
CREATE TABLE configuration_revisions (
    configuration_id VARCHAR(191) NOT NULL,
    revision INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    updated_by VARCHAR(191),
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(configuration_id, revision)
);
CREATE TABLE agent_configuration_state (
    agent_id VARCHAR(191) NOT NULL,
    configuration_id VARCHAR(191) NOT NULL,
    desired_revision INTEGER NOT NULL,
    applied_revision INTEGER,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    applied_checksum VARCHAR(64),
    last_error TEXT,
    reported_at VARCHAR(64),
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(agent_id, configuration_id),
    CONSTRAINT fk_agent_configuration_state_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX idx_configurations_scope_namespace ON configurations(scope_type, scope_key, namespace);
CREATE INDEX idx_configuration_revisions_created ON configuration_revisions(configuration_id, revision DESC);
CREATE INDEX idx_agent_configuration_state_pending ON agent_configuration_state(agent_id, status, desired_revision);
