-- Capivara DSM - Migration 029 - PostgreSQL
-- Durable Controller -> Agent queue for instance service provisioning.

CREATE TABLE IF NOT EXISTS agent_instance_provisioning_jobs (
    job_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    instance_id VARCHAR(191) NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    action VARCHAR(16) NOT NULL CHECK (action IN ('provision','reconcile','remove')),
    status VARCHAR(16) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    request_json TEXT NOT NULL,
    result_json TEXT,
    requested_by VARCHAR(191),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_instance_provisioning_agent_status
    ON agent_instance_provisioning_jobs(agent_id,status,created_at);
CREATE INDEX IF NOT EXISTS idx_agent_instance_provisioning_instance
    ON agent_instance_provisioning_jobs(instance_id,created_at);
