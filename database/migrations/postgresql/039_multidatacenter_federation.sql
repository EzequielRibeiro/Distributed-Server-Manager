CREATE TABLE IF NOT EXISTS federation_controllers (
    controller_id TEXT PRIMARY KEY,
    region_id TEXT,
    datacenter_id TEXT,
    endpoint TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'datacenter',
    status TEXT NOT NULL DEFAULT 'unknown',
    priority INTEGER NOT NULL DEFAULT 100,
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_federation_controllers_location ON federation_controllers(region_id, datacenter_id, status);
CREATE TABLE IF NOT EXISTS federation_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    checksum TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE(controller_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_federation_snapshots_controller ON federation_snapshots(controller_id, sequence DESC);
CREATE TABLE IF NOT EXISTS federation_routes (
    route_id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    controller_id TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope_type, scope_id, controller_id)
);
CREATE INDEX IF NOT EXISTS idx_federation_routes_scope ON federation_routes(scope_type, scope_id, enabled, priority);
