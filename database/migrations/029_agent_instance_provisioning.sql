-- Capivara DSM - Migration 029 - SQLite
-- Durable Controller -> Agent queue for instance service provisioning.

CREATE TABLE IF NOT EXISTS agent_instance_provisioning_jobs (
    job_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('provision','reconcile','remove')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    request_json TEXT NOT NULL,
    result_json TEXT,
    requested_by TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_instance_provisioning_agent_status
    ON agent_instance_provisioning_jobs(agent_id,status,created_at);
CREATE INDEX IF NOT EXISTS idx_agent_instance_provisioning_instance
    ON agent_instance_provisioning_jobs(instance_id,created_at);
