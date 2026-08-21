-- Capivara DSM - Migration 030 - MySQL
CREATE TABLE agent_instance_reconciliation (
    instance_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    desired_state VARCHAR(32) NULL,
    observed_state VARCHAR(32) NULL,
    reconcile_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    retry_count INT NOT NULL DEFAULT 0,
    last_attempt_at VARCHAR(64) NULL,
    last_success_at VARCHAR(64) NULL,
    next_retry_at VARCHAR(64) NULL,
    last_error TEXT NULL,
    drift VARCHAR(128) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_reconcile_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT fk_reconcile_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX idx_agent_instance_reconciliation_agent_status
    ON agent_instance_reconciliation(agent_id,reconcile_status,updated_at);
