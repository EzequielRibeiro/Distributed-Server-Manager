CREATE TABLE IF NOT EXISTS automation_rules (
 rule_id VARCHAR(191) PRIMARY KEY, name VARCHAR(191) NOT NULL, enabled TINYINT NOT NULL DEFAULT 1, trigger_json LONGTEXT NOT NULL,
 conditions_json LONGTEXT NOT NULL, actions_json LONGTEXT NOT NULL, cooldown_seconds INT NOT NULL DEFAULT 0,
 revision INT NOT NULL, checksum VARCHAR(64) NOT NULL, requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_rule_revisions (
 rule_id VARCHAR(191) NOT NULL, revision INT NOT NULL, name VARCHAR(191) NOT NULL, enabled TINYINT NOT NULL, trigger_json LONGTEXT NOT NULL,
 conditions_json LONGTEXT NOT NULL, actions_json LONGTEXT NOT NULL, cooldown_seconds INT NOT NULL, checksum VARCHAR(64) NOT NULL,
 requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, PRIMARY KEY(rule_id,revision),
 FOREIGN KEY(rule_id) REFERENCES automation_rules(rule_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS automation_runs (
 run_id VARCHAR(191) PRIMARY KEY, rule_id VARCHAR(191), trigger_type VARCHAR(32) NOT NULL, trigger_ref VARCHAR(191), status VARCHAR(32) NOT NULL DEFAULT 'pending',
 context_json LONGTEXT NOT NULL, result_json LONGTEXT NOT NULL, requested_by VARCHAR(191), started_at VARCHAR(40), completed_at VARCHAR(40), created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
 INDEX idx_automation_runs_rule_created(rule_id,created_at)
);
CREATE TABLE IF NOT EXISTS broadcasts (
 broadcast_id VARCHAR(191) PRIMARY KEY, scope VARCHAR(32) NOT NULL, target VARCHAR(191), message TEXT NOT NULL, priority VARCHAR(16) NOT NULL,
 ttl_seconds INT NOT NULL, require_ack TINYINT NOT NULL DEFAULT 1, status VARCHAR(32) NOT NULL DEFAULT 'pending', requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, expires_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS broadcast_deliveries (
 delivery_id VARCHAR(191) PRIMARY KEY, broadcast_id VARCHAR(191) NOT NULL, agent_id VARCHAR(191) NOT NULL, instance_id VARCHAR(191),
 status VARCHAR(32) NOT NULL DEFAULT 'pending', attempts INT NOT NULL DEFAULT 0, delivered_at VARCHAR(40), acknowledged_at VARCHAR(40), last_error TEXT, updated_at VARCHAR(40) NOT NULL,
 UNIQUE KEY uq_broadcast_delivery(broadcast_id,agent_id,instance_id), INDEX idx_broadcast_delivery_agent_status(agent_id,status,updated_at),
 FOREIGN KEY(broadcast_id) REFERENCES broadcasts(broadcast_id) ON DELETE CASCADE, FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
