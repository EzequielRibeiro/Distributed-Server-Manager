CREATE TABLE IF NOT EXISTS ha_clusters (
    cluster_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'manual',
    rpo_seconds INTEGER NOT NULL DEFAULT 300,
    rto_seconds INTEGER NOT NULL DEFAULT 900,
    quorum_size INTEGER NOT NULL DEFAULT 2,
    auto_failback BOOLEAN NOT NULL DEFAULT FALSE,
    fencing_epoch BIGINT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ha_cluster_members (
    cluster_id TEXT NOT NULL,
    controller_id TEXT NOT NULL,
    role TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'unknown',
    priority INTEGER NOT NULL DEFAULT 100,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(cluster_id, controller_id)
);
CREATE INDEX IF NOT EXISTS idx_ha_members_state ON ha_cluster_members(cluster_id, role, state, priority);
CREATE TABLE IF NOT EXISTS dr_recovery_points (
    recovery_point_id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    source_controller_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    location TEXT NOT NULL,
    checksum TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    validated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dr_points_cluster ON dr_recovery_points(cluster_id, created_at DESC);
CREATE TABLE IF NOT EXISTS ha_failover_operations (
    operation_id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    source_controller_id TEXT,
    target_controller_id TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT,
    requested_by TEXT,
    automatic BOOLEAN NOT NULL DEFAULT FALSE,
    fencing_epoch BIGINT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ha_failover_cluster ON ha_failover_operations(cluster_id, created_at DESC);
