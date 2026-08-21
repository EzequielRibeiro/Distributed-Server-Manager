CREATE TABLE IF NOT EXISTS backup_policies (
 policy_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL UNIQUE REFERENCES instances(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE, enabled BOOLEAN NOT NULL DEFAULT TRUE,
 mode TEXT NOT NULL, consistency TEXT NOT NULL, compression TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
 retention_count INTEGER NOT NULL, include_json TEXT NOT NULL DEFAULT '[]', exclude_json TEXT NOT NULL DEFAULT '[]',
 revision INTEGER NOT NULL, checksum TEXT NOT NULL, requested_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backup_policy_revisions (
 policy_id TEXT NOT NULL REFERENCES backup_policies(policy_id) ON DELETE CASCADE, revision INTEGER NOT NULL,
 enabled BOOLEAN NOT NULL, mode TEXT NOT NULL, consistency TEXT NOT NULL, compression TEXT NOT NULL,
 interval_seconds INTEGER NOT NULL, retention_count INTEGER NOT NULL, include_json TEXT NOT NULL, exclude_json TEXT NOT NULL,
 checksum TEXT NOT NULL, requested_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY(policy_id,revision)
);
CREATE TABLE IF NOT EXISTS backup_jobs (
 command_id TEXT PRIMARY KEY, backup_id TEXT UNIQUE, instance_id TEXT NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE, action TEXT NOT NULL, policy_revision INTEGER,
 status TEXT NOT NULL DEFAULT 'pending', reason TEXT, requested_by TEXT, size_bytes BIGINT, sha256 TEXT, artifact_path TEXT,
 started_at TEXT, completed_at TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backup_jobs_agent_status ON backup_jobs(agent_id,status,created_at);
CREATE INDEX IF NOT EXISTS idx_backup_jobs_instance_completed ON backup_jobs(instance_id,completed_at);
