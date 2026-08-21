-- Capivara DSM - Migration 029 - PostgreSQL
-- B10 persistent Controller -> Agent instance provisioning pipeline.

CREATE TABLE agent_instance_provisioning (
    provisioning_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    instance_id TEXT NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    environment_id TEXT NOT NULL,
    selector TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','delivered','running','completed','failed')),
    current_step TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_instance_provisioning_agent_status
    ON agent_instance_provisioning(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_provisioning_instance
    ON agent_instance_provisioning(instance_id,created_at);
