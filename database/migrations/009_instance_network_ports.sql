-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 009
-- Instance network port reservations
-- =============================================================

CREATE TABLE instance_ports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    instance_id TEXT NOT NULL,
    node_id TEXT NOT NULL,

    name TEXT NOT NULL,

    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'udp')),

    port INTEGER NOT NULL
        CHECK (port BETWEEN 1 AND 65535),

    bind_address TEXT NOT NULL DEFAULT '0.0.0.0',

    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE,

    FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE CASCADE,

    UNIQUE (instance_id, name, protocol),

    UNIQUE (node_id, protocol, port)
);

CREATE INDEX idx_instance_ports_instance
    ON instance_ports(instance_id);

CREATE INDEX idx_instance_ports_node
    ON instance_ports(node_id);

CREATE INDEX idx_instance_ports_node_protocol_port
    ON instance_ports(node_id, protocol, port);
