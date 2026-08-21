-- Capivara DSM - Migration 027 - PostgreSQL
CREATE TABLE agent_instance_commands (
    command_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    instance_id VARCHAR(191) NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    action VARCHAR(16) NOT NULL CHECK (action IN ('status','doctor')),
    status VARCHAR(16) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    requested_by VARCHAR(191),
    result_json TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_agent_instance_commands_agent_status ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance ON agent_instance_commands(instance_id,created_at);
