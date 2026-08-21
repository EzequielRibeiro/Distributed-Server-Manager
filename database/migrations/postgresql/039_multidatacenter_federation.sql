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

CREATE TABLE IF NOT EXISTS federation_credentials (
    credential_id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL REFERENCES federation_controllers(controller_id) ON DELETE CASCADE,
    token_prefix TEXT NOT NULL UNIQUE,
    secret_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    expires_at TEXT,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_federation_credentials_controller ON federation_credentials(controller_id, status);

CREATE TABLE IF NOT EXISTS federation_request_nonces (
    controller_id TEXT NOT NULL REFERENCES federation_controllers(controller_id) ON DELETE CASCADE,
    nonce TEXT NOT NULL,
    request_timestamp TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY(controller_id, nonce)
);
CREATE INDEX IF NOT EXISTS idx_federation_request_nonces_received ON federation_request_nonces(received_at);

CREATE TABLE IF NOT EXISTS federation_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL REFERENCES federation_controllers(controller_id) ON DELETE CASCADE,
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
    controller_id TEXT NOT NULL REFERENCES federation_controllers(controller_id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope_type, scope_id, controller_id)
);
CREATE INDEX IF NOT EXISTS idx_federation_routes_scope ON federation_routes(scope_type, scope_id, enabled, priority);

CREATE TABLE IF NOT EXISTS federation_event_cursors (
    controller_id TEXT PRIMARY KEY REFERENCES federation_controllers(controller_id) ON DELETE CASCADE,
    last_sequence BIGINT NOT NULL DEFAULT -1,
    last_event_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS federation_event_receipts (
    controller_id TEXT NOT NULL REFERENCES federation_controllers(controller_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    checksum TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY(controller_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_federation_event_receipts_time ON federation_event_receipts(received_at);

CREATE TABLE IF NOT EXISTS federation_handoffs (
    handoff_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    source_controller_id TEXT,
    target_controller_id TEXT NOT NULL REFERENCES federation_controllers(controller_id) ON DELETE RESTRICT,
    instance_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    checksum TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_federation_handoffs_target_status ON federation_handoffs(target_controller_id, status, created_at);
