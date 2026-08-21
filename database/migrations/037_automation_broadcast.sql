CREATE TABLE IF NOT EXISTS automation_rules (
 rule_id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, trigger_json TEXT NOT NULL,
 conditions_json TEXT NOT NULL DEFAULT '[]', actions_json TEXT NOT NULL, cooldown_seconds INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL, checksum TEXT NOT NULL, requested_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_rule_revisions (
 rule_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL, trigger_json TEXT NOT NULL,
 conditions_json TEXT NOT NULL, actions_json TEXT NOT NULL, cooldown_seconds INTEGER NOT NULL, checksum TEXT NOT NULL,
 requested_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY(rule_id,revision),
 FOREIGN KEY(rule_id) REFERENCES automation_rules(rule_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS automation_runs (
 run_id TEXT PRIMARY KEY, rule_id TEXT, trigger_type TEXT NOT NULL, trigger_ref TEXT, status TEXT NOT NULL DEFAULT 'pending',
 context_json TEXT NOT NULL DEFAULT '{}', result_json TEXT NOT NULL DEFAULT '{}', requested_by TEXT,
 started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automation_runs_rule_created ON automation_runs(rule_id,created_at);
CREATE TABLE IF NOT EXISTS broadcasts (
 broadcast_id TEXT PRIMARY KEY, scope TEXT NOT NULL, target TEXT, message TEXT NOT NULL, priority TEXT NOT NULL,
 ttl_seconds INTEGER NOT NULL, require_ack INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending',
 requested_by TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broadcast_deliveries (
 delivery_id TEXT PRIMARY KEY, broadcast_id TEXT NOT NULL, agent_id TEXT NOT NULL, instance_id TEXT,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, delivered_at TEXT, acknowledged_at TEXT,
 last_error TEXT, updated_at TEXT NOT NULL, UNIQUE(broadcast_id,agent_id,instance_id),
 FOREIGN KEY(broadcast_id) REFERENCES broadcasts(broadcast_id) ON DELETE CASCADE,
 FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_broadcast_delivery_agent_status ON broadcast_deliveries(agent_id,status,updated_at);
