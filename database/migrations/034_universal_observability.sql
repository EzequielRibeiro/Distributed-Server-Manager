-- Capivara DSM - Migration 034 - SQLite
-- Universal Observability Platform.

CREATE TABLE observability_samples (
    sample_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('agent','instance')),
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL CHECK (metric_type IN ('gauge','counter')),
    value_double REAL NOT NULL,
    unit TEXT NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    collected_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE observability_latest (
    agent_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    dimensions_key TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    value_double REAL NOT NULL,
    unit TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(agent_id, subject_key, metric_name, dimensions_key)
);

CREATE INDEX idx_observability_samples_agent_time ON observability_samples(agent_id, collected_at DESC);
CREATE INDEX idx_observability_samples_instance_time ON observability_samples(instance_id, collected_at DESC);
CREATE INDEX idx_observability_samples_metric_time ON observability_samples(metric_name, collected_at DESC);
CREATE INDEX idx_observability_latest_agent ON observability_latest(agent_id, subject_key, metric_name);
