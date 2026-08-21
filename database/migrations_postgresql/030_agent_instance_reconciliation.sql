-- Capivara DSM - Migration 030 - PostgreSQL
CREATE TABLE agent_instance_reconciliation (
    instance_id TEXT PRIMARY KEY REFERENCES instances(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    desired_state TEXT,
    observed_state TEXT,
    reconcile_status TEXT NOT NULL DEFAULT 'unknown',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_success_at TEXT,
    next_retry_at TEXT,
    last_error TEXT,
    drift TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_agent_instance_reconciliation_agent_status
    ON agent_instance_reconciliation(agent_id,reconcile_status,updated_at);
