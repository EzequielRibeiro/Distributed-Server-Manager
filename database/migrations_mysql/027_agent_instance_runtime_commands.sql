-- Capivara DSM - Migration 027 - MySQL/MariaDB
CREATE TABLE agent_instance_commands (
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
    CONSTRAINT fk_agent_instance_commands_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_commands_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_commands_action CHECK (action IN ('status','doctor')),
    CONSTRAINT chk_agent_instance_commands_status CHECK (status IN ('queued','delivered','completed','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_agent_instance_commands_agent_status ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance ON agent_instance_commands(instance_id,created_at);
