CREATE TABLE IF NOT EXISTS federation_controllers (
    controller_id VARCHAR(191) PRIMARY KEY,
    region_id VARCHAR(191),
    datacenter_id VARCHAR(191),
    endpoint TEXT NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'datacenter',
    status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    priority INTEGER NOT NULL DEFAULT 100,
    capabilities_json LONGTEXT NOT NULL,
    last_seen_at VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);
CREATE INDEX idx_federation_controllers_location ON federation_controllers(region_id, datacenter_id, status);
CREATE TABLE IF NOT EXISTS federation_snapshots (
    snapshot_id VARCHAR(191) PRIMARY KEY,
    controller_id VARCHAR(191) NOT NULL,
    generated_at VARCHAR(64) NOT NULL,
    sequence BIGINT NOT NULL,
    checksum VARCHAR(128) NOT NULL,
    payload_json LONGTEXT NOT NULL,
    received_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uq_federation_snapshot_sequence (controller_id, sequence)
);
CREATE INDEX idx_federation_snapshots_controller ON federation_snapshots(controller_id, sequence);
CREATE TABLE IF NOT EXISTS federation_routes (
    route_id VARCHAR(191) PRIMARY KEY,
    scope_type VARCHAR(32) NOT NULL,
    scope_id VARCHAR(191) NOT NULL,
    controller_id VARCHAR(191) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uq_federation_route (scope_type, scope_id, controller_id)
);
CREATE INDEX idx_federation_routes_scope ON federation_routes(scope_type, scope_id, enabled, priority);
