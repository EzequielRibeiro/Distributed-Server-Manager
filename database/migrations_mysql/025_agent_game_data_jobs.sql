-- Capivara DSM - Migration 025 - MySQL/MariaDB
-- Agent-owned game-data command queue.

CREATE TABLE agent_game_data_jobs (
    job_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    action VARCHAR(16) NOT NULL,
    environment_id VARCHAR(191) NOT NULL,
    selector VARCHAR(191) NOT NULL,
    selection_json LONGTEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    requested_by VARCHAR(191),
    result_json LONGTEXT,
    last_error TEXT,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at TIMESTAMP(6) NULL,
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_game_data_jobs_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_game_data_jobs_action
        CHECK (action IN ('install','update','verify')),
    CONSTRAINT chk_agent_game_data_jobs_status
        CHECK (status IN ('queued','delivered','running','completed','failed')),
    CONSTRAINT chk_agent_game_data_jobs_progress
        CHECK (progress >= 0 AND progress <= 100)
);

CREATE INDEX idx_agent_game_data_jobs_agent_status
    ON agent_game_data_jobs(agent_id,status,created_at);

CREATE INDEX idx_agent_game_data_jobs_environment
    ON agent_game_data_jobs(agent_id,environment_id,status);
