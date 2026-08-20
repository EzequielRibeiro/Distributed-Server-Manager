-- Capivara DSM - Migration 024 - PostgreSQL
CREATE TABLE agent_update_state (
    agent_id TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    installed_version TEXT,
    available_version TEXT,
    update_channel TEXT NOT NULL DEFAULT 'stable'
        CHECK (update_channel IN ('stable','beta','local/manual')),
    desired_version TEXT,
    update_status TEXT NOT NULL DEFAULT 'idle'
        CHECK (update_status IN ('idle','planned','updating','verifying','completed','failed')),
    rollout_id TEXT,
    batch_number INTEGER,
    batch_position INTEGER,
    requested_at TEXT,
    last_update TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::TEXT
);
CREATE INDEX idx_agent_update_rollout ON agent_update_state(rollout_id,batch_number,batch_position);
CREATE INDEX idx_agent_update_status ON agent_update_state(update_status,update_channel);
