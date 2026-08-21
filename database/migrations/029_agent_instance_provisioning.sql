-- Capivara DSM - Migration 029 - SQLite
-- B10 persistent Controller -> Agent instance provisioning pipeline.

CREATE TABLE agent_instance_provisioning (
    provisioning_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_instance_provisioning_agent_status
    ON agent_instance_provisioning(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_provisioning_instance
    ON agent_instance_provisioning(instance_id,created_at);
