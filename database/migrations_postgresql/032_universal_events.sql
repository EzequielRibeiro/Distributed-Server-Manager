-- Capivara DSM - Migration 032 - PostgreSQL
CREATE TABLE universal_events (
    event_id VARCHAR(191) PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    event_type VARCHAR(128) NOT NULL,
    occurred_at VARCHAR(64) NOT NULL,
    received_at VARCHAR(64) NOT NULL,
    source VARCHAR(128) NOT NULL,
    source_id VARCHAR(191),
    severity VARCHAR(16) NOT NULL DEFAULT 'info',
    agent_id VARCHAR(191),
    instance_id VARCHAR(191),
    correlation_id VARCHAR(191),
    causation_id VARCHAR(191),
    actor_type VARCHAR(64),
    actor_id VARCHAR(191),
    data_json TEXT NOT NULL,
    CONSTRAINT fk_universal_events_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL,
    CONSTRAINT fk_universal_events_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE SET NULL
);
CREATE INDEX idx_universal_events_type_time ON universal_events(event_type, occurred_at);
CREATE INDEX idx_universal_events_agent_time ON universal_events(agent_id, occurred_at);
CREATE INDEX idx_universal_events_instance_time ON universal_events(instance_id, occurred_at);
CREATE INDEX idx_universal_events_severity_time ON universal_events(severity, occurred_at);
CREATE INDEX idx_universal_events_correlation ON universal_events(correlation_id, occurred_at);
