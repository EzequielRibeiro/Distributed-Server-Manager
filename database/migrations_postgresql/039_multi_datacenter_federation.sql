-- Capivara DSM - Migration 039 - PostgreSQL
-- E1 Multi-Datacenter Federation.
CREATE TABLE IF NOT EXISTS federation_members (
 controller_id TEXT PRIMARY KEY REFERENCES controllers(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK (role IN ('global','regional','datacenter')),
 region_id TEXT REFERENCES regions(id) ON DELETE RESTRICT,
 datacenter_id TEXT REFERENCES datacenters(id) ON DELETE RESTRICT,
 public_endpoint TEXT, credential_hash TEXT,
 status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','degraded','offline','disabled')),
 last_seen_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_federation_members_location ON federation_members(region_id,datacenter_id,status);
CREATE TABLE IF NOT EXISTS federation_inventory_snapshots (
 snapshot_id TEXT PRIMARY KEY, controller_id TEXT NOT NULL REFERENCES federation_members(controller_id) ON DELETE CASCADE,
 generated_at TEXT NOT NULL, payload_json TEXT NOT NULL, received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_federation_inventory_member_time ON federation_inventory_snapshots(controller_id,generated_at DESC);
CREATE TABLE IF NOT EXISTS federation_policies (
 policy_id TEXT PRIMARY KEY, scope_type TEXT NOT NULL CHECK (scope_type IN ('global','region','datacenter','customer')),
 scope_id TEXT, mode TEXT NOT NULL DEFAULT 'local_first' CHECK (mode IN ('local_first','region_first','global')),
 cross_region_fallback INTEGER NOT NULL DEFAULT 0 CHECK (cross_region_fallback IN (0,1)), max_latency_ms INTEGER,
 payload_json TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_federation_policies_scope ON federation_policies(scope_type,scope_id);
CREATE TABLE IF NOT EXISTS federation_event_cursors (
 controller_id TEXT PRIMARY KEY REFERENCES federation_members(controller_id) ON DELETE CASCADE,
 last_event_id TEXT, updated_at TEXT NOT NULL
);
