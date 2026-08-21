-- Capivara DSM - Migration 039 - MySQL/MariaDB
-- E1 Multi-Datacenter Federation.
CREATE TABLE IF NOT EXISTS federation_members (
 controller_id VARCHAR(191) PRIMARY KEY,
 role VARCHAR(32) NOT NULL, region_id VARCHAR(191) NULL, datacenter_id VARCHAR(191) NULL,
 public_endpoint TEXT NULL, credential_hash TEXT NULL, status VARCHAR(32) NOT NULL DEFAULT 'pending',
 last_seen_at VARCHAR(64) NULL, created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_fed_member_controller FOREIGN KEY(controller_id) REFERENCES controllers(id) ON DELETE CASCADE,
 CONSTRAINT fk_fed_member_region FOREIGN KEY(region_id) REFERENCES regions(id) ON DELETE RESTRICT,
 CONSTRAINT fk_fed_member_dc FOREIGN KEY(datacenter_id) REFERENCES datacenters(id) ON DELETE RESTRICT
);
CREATE INDEX idx_federation_members_location ON federation_members(region_id,datacenter_id,status);
CREATE TABLE IF NOT EXISTS federation_inventory_snapshots (
 snapshot_id VARCHAR(191) PRIMARY KEY, controller_id VARCHAR(191) NOT NULL,
 generated_at VARCHAR(64) NOT NULL, payload_json LONGTEXT NOT NULL, received_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_fed_snapshot_member FOREIGN KEY(controller_id) REFERENCES federation_members(controller_id) ON DELETE CASCADE
);
CREATE INDEX idx_federation_inventory_member_time ON federation_inventory_snapshots(controller_id,generated_at);
CREATE TABLE IF NOT EXISTS federation_policies (
 policy_id VARCHAR(191) PRIMARY KEY, scope_type VARCHAR(32) NOT NULL, scope_id VARCHAR(191) NULL,
 mode VARCHAR(32) NOT NULL DEFAULT 'local_first', cross_region_fallback TINYINT NOT NULL DEFAULT 0,
 max_latency_ms INT NULL, payload_json LONGTEXT NOT NULL, revision INT NOT NULL DEFAULT 1,
 created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL
);
CREATE INDEX idx_federation_policies_scope ON federation_policies(scope_type,scope_id);
CREATE TABLE IF NOT EXISTS federation_event_cursors (
 controller_id VARCHAR(191) PRIMARY KEY, last_event_id VARCHAR(191) NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_fed_cursor_member FOREIGN KEY(controller_id) REFERENCES federation_members(controller_id) ON DELETE CASCADE
);
