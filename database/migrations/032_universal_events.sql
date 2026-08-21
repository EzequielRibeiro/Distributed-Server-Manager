-- Capivara DSM - Migration 032 - SQLite
-- Durable normalized store for the Universal Event Platform.
-- Subject identifiers intentionally have no foreign keys: immutable event history
-- must survive deletion or re-creation of mutable infrastructure entities.

CREATE TABLE universal_events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source TEXT NOT NULL,
    source_id TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    agent_id TEXT,
    instance_id TEXT,
    correlation_id TEXT,
    causation_id TEXT,
    actor_type TEXT,
    actor_id TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_universal_events_type_time
    ON universal_events(event_type, occurred_at);
CREATE INDEX idx_universal_events_agent_time
    ON universal_events(agent_id, occurred_at);
CREATE INDEX idx_universal_events_instance_time
    ON universal_events(instance_id, occurred_at);
CREATE INDEX idx_universal_events_severity_time
    ON universal_events(severity, occurred_at);
CREATE INDEX idx_universal_events_correlation
    ON universal_events(correlation_id, occurred_at);
