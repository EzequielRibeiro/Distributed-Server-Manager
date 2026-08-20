-- Capivara DSM - Migration 024 - MySQL/MariaDB
CREATE TABLE agent_update_state (
    agent_id VARCHAR(191) PRIMARY KEY,
    installed_version VARCHAR(64),
    available_version VARCHAR(64),
    update_channel VARCHAR(32) NOT NULL DEFAULT 'stable',
    desired_version VARCHAR(64),
    update_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    rollout_id VARCHAR(191),
    batch_number INTEGER,
    batch_position INTEGER,
    requested_at VARCHAR(64),
    last_update VARCHAR(64),
    last_error TEXT,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_agent_update_state_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_update_channel CHECK (update_channel IN ('stable','beta','local/manual')),
    CONSTRAINT chk_agent_update_status CHECK (update_status IN ('idle','planned','updating','verifying','completed','failed'))
);
CREATE INDEX idx_agent_update_rollout ON agent_update_state(rollout_id,batch_number,batch_position);
CREATE INDEX idx_agent_update_status ON agent_update_state(update_status,update_channel);
