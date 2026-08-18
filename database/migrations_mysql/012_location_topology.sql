-- =============================================================
-- Capivara DSM MySQL / MariaDB Migration 012
-- =============================================================

CREATE TABLE regions (
    id VARCHAR(191) NOT NULL,
    name VARCHAR(191) NOT NULL,
    country_code VARCHAR(8),
    continent_code VARCHAR(8),
    latitude DOUBLE,
    longitude DOUBLE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT chk_regions_status
        CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE datacenters (
    id VARCHAR(191) NOT NULL,
    region_id VARCHAR(191) NOT NULL,
    name VARCHAR(191) NOT NULL,
    provider VARCHAR(191),
    city VARCHAR(191),
    country_code VARCHAR(8),
    latitude DOUBLE,
    longitude DOUBLE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_datacenters_region
        FOREIGN KEY (region_id)
        REFERENCES regions(id)
        ON DELETE RESTRICT,
    CONSTRAINT chk_datacenters_status
        CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE agent_locations (
    agent_id VARCHAR(191) NOT NULL,
    datacenter_id VARCHAR(191) NOT NULL,
    latitude DOUBLE,
    longitude DOUBLE,
    public_host VARCHAR(255),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (agent_id),
    CONSTRAINT fk_agent_locations_agent
        FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_agent_locations_datacenter
        FOREIGN KEY (datacenter_id)
        REFERENCES datacenters(id)
        ON DELETE RESTRICT,
    CONSTRAINT chk_agent_locations_status
        CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE controller_placement_policies (
    controller_id VARCHAR(191) NOT NULL,
    mode VARCHAR(32) NOT NULL DEFAULT 'latency_assisted',
    customer_region_selection BOOLEAN NOT NULL DEFAULT TRUE,
    cross_region_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    max_latency_ms INTEGER,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (controller_id),
    CONSTRAINT chk_placement_policy_mode
        CHECK (mode IN (
            'controller',
            'customer_region',
            'latency_assisted'
        ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_datacenters_region
    ON datacenters(region_id, status);

CREATE INDEX idx_agent_locations_datacenter
    ON agent_locations(datacenter_id, status);
