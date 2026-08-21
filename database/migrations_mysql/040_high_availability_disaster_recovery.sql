CREATE TABLE IF NOT EXISTS ha_clusters (
    cluster_id VARCHAR(191) PRIMARY KEY,
    name VARCHAR(191) NOT NULL,
    mode VARCHAR(32) NOT NULL DEFAULT 'manual',
    rpo_seconds INTEGER NOT NULL DEFAULT 300,
    rto_seconds INTEGER NOT NULL DEFAULT 900,
    quorum_size INTEGER NOT NULL DEFAULT 2,
    auto_failback BOOLEAN NOT NULL DEFAULT FALSE,
    fencing_epoch BIGINT NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);
CREATE TABLE IF NOT EXISTS ha_cluster_members (
    cluster_id VARCHAR(191) NOT NULL,
    controller_id VARCHAR(191) NOT NULL,
    role VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'unknown',
    priority INTEGER NOT NULL DEFAULT 100,
    last_seen_at VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(cluster_id, controller_id)
);
CREATE INDEX idx_ha_members_state ON ha_cluster_members(cluster_id, role, state, priority);
CREATE TABLE IF NOT EXISTS dr_recovery_points (
    recovery_point_id VARCHAR(191) PRIMARY KEY,
    cluster_id VARCHAR(191) NOT NULL,
    source_controller_id VARCHAR(191) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL,
    location TEXT NOT NULL,
    checksum VARCHAR(128),
    metadata_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    validated_at VARCHAR(64)
);
CREATE INDEX idx_dr_points_cluster ON dr_recovery_points(cluster_id, created_at);
CREATE TABLE IF NOT EXISTS ha_failover_operations (
    operation_id VARCHAR(191) PRIMARY KEY,
    cluster_id VARCHAR(191) NOT NULL,
    source_controller_id VARCHAR(191),
    target_controller_id VARCHAR(191) NOT NULL,
    state VARCHAR(32) NOT NULL,
    reason TEXT,
    requested_by VARCHAR(191),
    automatic BOOLEAN NOT NULL DEFAULT FALSE,
    fencing_epoch BIGINT NOT NULL,
    message TEXT,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    completed_at VARCHAR(64)
);
CREATE INDEX idx_ha_failover_cluster ON ha_failover_operations(cluster_id, created_at);
