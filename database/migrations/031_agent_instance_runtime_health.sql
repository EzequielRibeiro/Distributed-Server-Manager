-- Capivara DSM - Migration 031 - SQLite
-- Final Controller-side instance runtime health projection.

CREATE TABLE agent_instance_runtime_health (
    instance_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    desired_state TEXT,
    observed_state TEXT,
    reconcile_status TEXT NOT NULL DEFAULT 'unknown',
    health TEXT NOT NULL DEFAULT 'unknown',
    operation_status TEXT NOT NULL DEFAULT 'idle',
    operation_name TEXT,
    last_error TEXT,
    last_transition_at TEXT,
    reported_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_instance_runtime_health_agent
    ON agent_instance_runtime_health(agent_id,health,updated_at);
