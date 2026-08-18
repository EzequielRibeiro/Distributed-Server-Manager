-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 012
-- Geographic regions, datacenters and Agent placement
-- =============================================================

CREATE TABLE regions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT,
    continent_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

CREATE TABLE datacenters (
    id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT,
    city TEXT,
    country_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (region_id)
        REFERENCES regions(id)
        ON DELETE RESTRICT
);

CREATE TABLE agent_locations (
    agent_id TEXT PRIMARY KEY,
    datacenter_id TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    public_host TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,
    FOREIGN KEY (datacenter_id)
        REFERENCES datacenters(id)
        ON DELETE RESTRICT
);

CREATE TABLE controller_placement_policies (
    controller_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'latency_assisted'
        CHECK (mode IN (
            'controller',
            'customer_region',
            'latency_assisted'
        )),
    customer_region_selection INTEGER NOT NULL DEFAULT 1
        CHECK (customer_region_selection IN (0, 1)),
    cross_region_fallback INTEGER NOT NULL DEFAULT 0
        CHECK (cross_region_fallback IN (0, 1)),
    max_latency_ms INTEGER,
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

CREATE INDEX idx_datacenters_region
    ON datacenters(region_id, status);

CREATE INDEX idx_agent_locations_datacenter
    ON agent_locations(datacenter_id, status);
