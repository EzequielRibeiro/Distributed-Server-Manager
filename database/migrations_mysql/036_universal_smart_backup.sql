CREATE TABLE IF NOT EXISTS backup_policies (
 policy_id VARCHAR(191) PRIMARY KEY, instance_id VARCHAR(191) NOT NULL UNIQUE, agent_id VARCHAR(191) NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
 mode VARCHAR(32) NOT NULL, consistency VARCHAR(32) NOT NULL, compression VARCHAR(32) NOT NULL, interval_seconds INT NOT NULL,
 retention_count INT NOT NULL, include_json LONGTEXT NOT NULL, exclude_json LONGTEXT NOT NULL, revision INT NOT NULL, checksum VARCHAR(64) NOT NULL,
 requested_by VARCHAR(191), created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_backup_policy_instance FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE,
 CONSTRAINT fk_backup_policy_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS backup_policy_revisions (
 policy_id VARCHAR(191) NOT NULL, revision INT NOT NULL, enabled BOOLEAN NOT NULL, mode VARCHAR(32) NOT NULL, consistency VARCHAR(32) NOT NULL,
 compression VARCHAR(32) NOT NULL, interval_seconds INT NOT NULL, retention_count INT NOT NULL, include_json LONGTEXT NOT NULL,
 exclude_json LONGTEXT NOT NULL, checksum VARCHAR(64) NOT NULL, requested_by VARCHAR(191), created_at VARCHAR(64) NOT NULL,
 PRIMARY KEY(policy_id,revision), CONSTRAINT fk_backup_revision_policy FOREIGN KEY(policy_id) REFERENCES backup_policies(policy_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS backup_jobs (
 command_id VARCHAR(191) PRIMARY KEY, backup_id VARCHAR(191) UNIQUE, instance_id VARCHAR(191) NOT NULL, agent_id VARCHAR(191) NOT NULL,
 action VARCHAR(32) NOT NULL, policy_revision INT, status VARCHAR(32) NOT NULL DEFAULT 'pending', reason VARCHAR(64), requested_by VARCHAR(191),
 size_bytes BIGINT, sha256 VARCHAR(64), artifact_path TEXT, started_at VARCHAR(64), completed_at VARCHAR(64), last_error TEXT,
 created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_backup_job_instance FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE,
 CONSTRAINT fk_backup_job_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE,
 INDEX idx_backup_jobs_agent_status(agent_id,status,created_at), INDEX idx_backup_jobs_instance_completed(instance_id,completed_at)
);
