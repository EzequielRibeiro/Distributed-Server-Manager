-- Capivara DSM - Migration 031 - PostgreSQL
CREATE TABLE agent_instance_runtime_health (
    instance_id TEXT PRIMARY KEY REFERENCES instances(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    desired_state TEXT,
    observed_state TEXT,
    reconcile_status TEXT NOT NULL DEFAULT 'unknown',
    health TEXT NOT NULL DEFAULT 'unknown',
    operation_status TEXT NOT NULL DEFAULT 'idle',
    operation_name TEXT,
    last_error TEXT,
    last_transition_at TEXT,
    reported_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_agent_instance_runtime_health_agent
    ON agent_instance_runtime_health(agent_id,health,updated_at);
