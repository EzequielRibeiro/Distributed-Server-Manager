-- Capivara DSM - Migration 029 - MySQL
-- B10 persistent Controller -> Agent instance provisioning pipeline.

CREATE TABLE agent_instance_provisioning (
    provisioning_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NOT NULL,
    environment_id VARCHAR(191) NOT NULL,
    selector VARCHAR(191) NOT NULL,
    request_json LONGTEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    current_step VARCHAR(128) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    requested_by VARCHAR(191) NULL,
    result_json LONGTEXT NULL,
    last_error TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at DATETIME(6) NULL,
    started_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_instance_provisioning_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_provisioning_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_provisioning_status CHECK (status IN ('queued','delivered','running','completed','failed')),
    CONSTRAINT chk_agent_instance_provisioning_progress CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX idx_agent_instance_provisioning_agent_status
    ON agent_instance_provisioning(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_provisioning_instance
    ON agent_instance_provisioning(instance_id,created_at);
