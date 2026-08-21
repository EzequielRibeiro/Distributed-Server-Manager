-- Capivara DSM - Migration 035 - SQLite
CREATE TABLE content_assignments (
 assignment_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, agent_id TEXT NOT NULL,
 content_id TEXT NOT NULL, game_id TEXT NOT NULL, content_type TEXT NOT NULL,
 desired_state TEXT NOT NULL CHECK(desired_state IN ('installed','absent')),
 version TEXT NOT NULL, provider TEXT NOT NULL, target TEXT NOT NULL,
 artifact_json TEXT NOT NULL DEFAULT '{}', dependencies_json TEXT NOT NULL DEFAULT '[]', conflicts_json TEXT NOT NULL DEFAULT '[]',
 revision INTEGER NOT NULL, checksum TEXT NOT NULL, requested_by TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(instance_id,content_id)
);
CREATE TABLE content_assignment_revisions (
 assignment_id TEXT NOT NULL, revision INTEGER NOT NULL, desired_state TEXT NOT NULL,
 version TEXT NOT NULL, provider TEXT NOT NULL, target TEXT NOT NULL, artifact_json TEXT NOT NULL,
 dependencies_json TEXT NOT NULL, conflicts_json TEXT NOT NULL, checksum TEXT NOT NULL,
 requested_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY(assignment_id,revision)
);
CREATE TABLE agent_content_state (
 agent_id TEXT NOT NULL, instance_id TEXT NOT NULL, content_id TEXT NOT NULL,
 desired_revision INTEGER NOT NULL, applied_revision INTEGER, desired_checksum TEXT NOT NULL, applied_checksum TEXT,
 status TEXT NOT NULL, installed_version TEXT, last_error TEXT, reported_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(agent_id,instance_id,content_id)
);
CREATE INDEX idx_content_assignments_agent ON content_assignments(agent_id,instance_id,desired_state);
CREATE INDEX idx_agent_content_state_agent ON agent_content_state(agent_id,status);
