-- Capivara DSM - Migration 029 - MySQL
-- Durable Controller -> Agent queue for instance service provisioning.

CREATE TABLE IF NOT EXISTS agent_instance_provisioning_jobs (
    job_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NOT NULL,
    action VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    request_json LONGTEXT NOT NULL,
    result_json LONGTEXT,
    requested_by VARCHAR(191),
    last_error TEXT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at DATETIME(6),
    completed_at DATETIME(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_instance_provisioning_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_provisioning_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_provisioning_action CHECK (action IN ('provision','reconcile','remove')),
    CONSTRAINT chk_agent_instance_provisioning_status CHECK (status IN ('queued','delivered','completed','failed')),
    INDEX idx_agent_instance_provisioning_agent_status (agent_id,status,created_at),
    INDEX idx_agent_instance_provisioning_instance (instance_id,created_at)
);
