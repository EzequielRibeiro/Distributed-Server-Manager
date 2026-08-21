-- Capivara DSM - Migration 034 - PostgreSQL
CREATE TABLE observability_samples (
    sample_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191),
    scope_type VARCHAR(32) NOT NULL CHECK (scope_type IN ('agent','instance')),
    metric_name VARCHAR(191) NOT NULL,
    metric_type VARCHAR(32) NOT NULL CHECK (metric_type IN ('gauge','counter')),
    value_double DOUBLE PRECISION NOT NULL,
    unit VARCHAR(32) NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    collected_at VARCHAR(64) NOT NULL,
    ingested_at VARCHAR(64) NOT NULL
);
CREATE TABLE observability_latest (
    agent_id VARCHAR(191) NOT NULL,
    subject_key VARCHAR(191) NOT NULL,
    metric_name VARCHAR(191) NOT NULL,
    dimensions_key VARCHAR(64) NOT NULL,
    sample_id VARCHAR(191) NOT NULL,
    value_double DOUBLE PRECISION NOT NULL,
    unit VARCHAR(32) NOT NULL,
    metric_type VARCHAR(32) NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    collected_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(agent_id, subject_key, metric_name, dimensions_key)
);
CREATE INDEX idx_observability_samples_agent_time ON observability_samples(agent_id, collected_at DESC);
CREATE INDEX idx_observability_samples_instance_time ON observability_samples(instance_id, collected_at DESC);
CREATE INDEX idx_observability_samples_metric_time ON observability_samples(metric_name, collected_at DESC);
CREATE INDEX idx_observability_latest_agent ON observability_latest(agent_id, subject_key, metric_name);
