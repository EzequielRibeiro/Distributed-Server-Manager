-- Capivara DSM - Migration 025
-- Agent-owned game-data command queue.

CREATE TABLE agent_game_data_jobs (
    job_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (action IN ('install','update','verify')),
    environment_id TEXT NOT NULL,
    selector TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','delivered','running','completed','failed')),
    progress INTEGER NOT NULL DEFAULT 0
        CHECK (progress >= 0 AND progress <= 100),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_game_data_jobs_agent_status
    ON agent_game_data_jobs(agent_id,status,created_at);

CREATE INDEX idx_agent_game_data_jobs_environment
    ON agent_game_data_jobs(agent_id,environment_id,status);
