-- =============================================================
-- Capivara DSM PostgreSQL Migration 012
-- =============================================================

CREATE TABLE regions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT,
    continent_code TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE datacenters (
    id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL
        REFERENCES regions(id)
        ON DELETE RESTRICT,
    name TEXT NOT NULL,
    provider TEXT,
    city TEXT,
    country_code TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_locations (
    agent_id TEXT PRIMARY KEY
        REFERENCES agents(id)
        ON DELETE CASCADE,
    datacenter_id TEXT NOT NULL
        REFERENCES datacenters(id)
        ON DELETE RESTRICT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    public_host TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE controller_placement_policies (
    controller_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'latency_assisted'
        CHECK (mode IN (
            'controller',
            'customer_region',
            'latency_assisted'
        )),
    customer_region_selection BOOLEAN NOT NULL DEFAULT TRUE,
    cross_region_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    max_latency_ms INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_datacenters_region
    ON datacenters(region_id, status);

CREATE INDEX idx_agent_locations_datacenter
    ON agent_locations(datacenter_id, status);
