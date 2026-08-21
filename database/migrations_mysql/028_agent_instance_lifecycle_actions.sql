-- Capivara DSM - Migration 028 - MySQL/MariaDB
-- Rebuild the B6 command table so lifecycle actions have an explicit allowlist.

CREATE TABLE agent_instance_commands_v2 (
    command_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NOT NULL,
    action VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    requested_by VARCHAR(191),
    result_json LONGTEXT,
    last_error TEXT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_instance_commands_v2_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_commands_v2_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_commands_v2_action CHECK (action IN ('status','doctor','start','stop','restart')),
    CONSTRAINT chk_agent_instance_commands_v2_status CHECK (status IN ('queued','delivered','completed','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO agent_instance_commands_v2
(command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at)
SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at
FROM agent_instance_commands;

DROP TABLE agent_instance_commands;
RENAME TABLE agent_instance_commands_v2 TO agent_instance_commands;

CREATE INDEX idx_agent_instance_commands_agent_status ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance ON agent_instance_commands(instance_id,created_at);
