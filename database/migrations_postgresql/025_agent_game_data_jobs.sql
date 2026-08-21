-- Capivara DSM - Migration 025 - PostgreSQL
-- Agent-owned game-data command queue.

CREATE TABLE agent_game_data_jobs (
    job_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('install','update','verify')),
    environment_id TEXT NOT NULL,
    selector TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','delivered','running','completed','failed')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_game_data_jobs_agent_status
    ON agent_game_data_jobs(agent_id,status,created_at);

CREATE INDEX idx_agent_game_data_jobs_environment
    ON agent_game_data_jobs(agent_id,environment_id,status);
