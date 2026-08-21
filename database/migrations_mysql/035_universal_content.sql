-- Capivara DSM - Migration 035 - MySQL/MariaDB
CREATE TABLE content_assignments (
 assignment_id VARCHAR(191) PRIMARY KEY, instance_id VARCHAR(191) NOT NULL, agent_id VARCHAR(191) NOT NULL,
 content_id VARCHAR(191) NOT NULL, game_id VARCHAR(191) NOT NULL, content_type VARCHAR(32) NOT NULL,
 desired_state VARCHAR(16) NOT NULL, version VARCHAR(191) NOT NULL, provider VARCHAR(64) NOT NULL, target VARCHAR(500) NOT NULL,
 artifact_json LONGTEXT NOT NULL, dependencies_json LONGTEXT NOT NULL, conflicts_json LONGTEXT NOT NULL,
 revision BIGINT NOT NULL, checksum CHAR(64) NOT NULL, requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
 UNIQUE KEY uq_content_instance_id(instance_id,content_id), KEY idx_content_assignments_agent(agent_id,instance_id,desired_state)
);
CREATE TABLE content_assignment_revisions (
 assignment_id VARCHAR(191) NOT NULL, revision BIGINT NOT NULL, desired_state VARCHAR(16) NOT NULL,
 version VARCHAR(191) NOT NULL, provider VARCHAR(64) NOT NULL, target VARCHAR(500) NOT NULL, artifact_json LONGTEXT NOT NULL,
 dependencies_json LONGTEXT NOT NULL, conflicts_json LONGTEXT NOT NULL, checksum CHAR(64) NOT NULL,
 requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, PRIMARY KEY(assignment_id,revision)
);
CREATE TABLE agent_content_state (
 agent_id VARCHAR(191) NOT NULL, instance_id VARCHAR(191) NOT NULL, content_id VARCHAR(191) NOT NULL,
 desired_revision BIGINT NOT NULL, applied_revision BIGINT, desired_checksum CHAR(64) NOT NULL, applied_checksum CHAR(64),
 status VARCHAR(32) NOT NULL, installed_version VARCHAR(191), last_error TEXT, reported_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
 PRIMARY KEY(agent_id,instance_id,content_id), KEY idx_agent_content_state_agent(agent_id,status)
);
