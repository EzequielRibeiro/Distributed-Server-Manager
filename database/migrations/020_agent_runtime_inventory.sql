-- Capivara DSM - Migration 020
-- Agent runtime inventory and heartbeat health are intentionally separated
-- from agents.status (administrative/lifecycle state).

CREATE TABLE agent_runtime_inventory (
    agent_id TEXT PRIMARY KEY,
    hostname TEXT,
    os_name TEXT,
    architecture TEXT,
    capivara_version TEXT,
    address TEXT,
    fingerprint TEXT,
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    cpu_json TEXT NOT NULL DEFAULT '{}',
    ram_total_bytes INTEGER,
    storage_json TEXT NOT NULL DEFAULT '{}',
    health_status TEXT NOT NULL DEFAULT 'offline'
        CHECK (health_status IN ('online', 'degraded', 'offline')),
    last_seen TEXT,
    heartbeat_interval_seconds INTEGER NOT NULL DEFAULT 30,
    degraded_after_seconds INTEGER NOT NULL DEFAULT 60,
    offline_after_seconds INTEGER NOT NULL DEFAULT 120,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CHECK (heartbeat_interval_seconds > 0),
    CHECK (degraded_after_seconds >= heartbeat_interval_seconds),
    CHECK (offline_after_seconds > degraded_after_seconds)
);

CREATE INDEX idx_agent_runtime_health
    ON agent_runtime_inventory(health_status, last_seen);

CREATE INDEX idx_agent_runtime_fingerprint
    ON agent_runtime_inventory(fingerprint);
