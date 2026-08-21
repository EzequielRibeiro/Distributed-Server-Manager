-- Capivara DSM - Migration 031 - MySQL
CREATE TABLE agent_instance_runtime_health (
    instance_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    desired_state VARCHAR(32) NULL,
    observed_state VARCHAR(32) NULL,
    reconcile_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    health VARCHAR(32) NOT NULL DEFAULT 'unknown',
    operation_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    operation_name VARCHAR(64) NULL,
    last_error TEXT NULL,
    last_transition_at VARCHAR(64) NULL,
    reported_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_runtime_health_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT fk_runtime_health_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX idx_agent_instance_runtime_health_agent
    ON agent_instance_runtime_health(agent_id,health,updated_at);
