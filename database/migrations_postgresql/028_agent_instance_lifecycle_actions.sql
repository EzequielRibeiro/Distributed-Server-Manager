-- Capivara DSM - Migration 028 - PostgreSQL
-- Rebuild the B6 command table so lifecycle actions have an explicit allowlist.

CREATE TABLE agent_instance_commands_v2 (
    command_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    instance_id VARCHAR(191) NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    action VARCHAR(16) NOT NULL CHECK (action IN ('status','doctor','start','stop','restart')),
    status VARCHAR(16) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    requested_by VARCHAR(191),
    result_json TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO agent_instance_commands_v2
(command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at)
SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at
FROM agent_instance_commands;

DROP TABLE agent_instance_commands;
ALTER TABLE agent_instance_commands_v2 RENAME TO agent_instance_commands;

CREATE INDEX idx_agent_instance_commands_agent_status ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance ON agent_instance_commands(instance_id,created_at);
