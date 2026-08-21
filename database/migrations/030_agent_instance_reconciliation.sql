-- Capivara DSM - Migration 030 - SQLite
-- Controller-side projection of Agent runtime reconciliation state.

CREATE TABLE agent_instance_reconciliation (
    instance_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    desired_state TEXT,
    observed_state TEXT,
    reconcile_status TEXT NOT NULL DEFAULT 'unknown',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_success_at TEXT,
    next_retry_at TEXT,
    last_error TEXT,
    drift TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_instance_reconciliation_agent_status
    ON agent_instance_reconciliation(agent_id,reconcile_status,updated_at);
