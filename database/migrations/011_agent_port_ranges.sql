
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 011
-- Agent managed network port ranges
-- =============================================================

CREATE TABLE agent_port_ranges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    agent_id TEXT NOT NULL,

    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'udp')),

    start_port INTEGER NOT NULL
        CHECK (start_port BETWEEN 1 AND 65535),

    end_port INTEGER NOT NULL
        CHECK (end_port BETWEEN 1 AND 65535),

    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),

    label TEXT,

    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    CHECK (start_port <= end_port),

    FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,

    UNIQUE (
        agent_id,
        protocol,
        start_port,
        end_port
    )
);

CREATE INDEX idx_agent_port_ranges_agent
    ON agent_port_ranges(agent_id);

CREATE INDEX idx_agent_port_ranges_lookup
    ON agent_port_ranges(
        agent_id,
        protocol,
        status,
        start_port,
        end_port
    );

-- Compatibilidade com a política anterior.
-- A faixa pode ser alterada posteriormente pelo administrador.
INSERT INTO agent_port_ranges(
    agent_id,
    protocol,
    start_port,
    end_port,
    status,
    label
)
SELECT
    id,
    'udp',
    24000,
    24999,
    'active',
    'default'
FROM agents;

INSERT INTO agent_port_ranges(
    agent_id,
    protocol,
    start_port,
    end_port,
    status,
    label
)
SELECT
    id,
    'tcp',
    24000,
    24999,
    'active',
    'default'
FROM agents;

-- Todo Agent criado depois da migration também recebe um
-- pool inicial administrável pelo Controller.
CREATE TRIGGER agents_default_port_ranges_insert
AFTER INSERT ON agents
BEGIN
    INSERT INTO agent_port_ranges(
        agent_id,
        protocol,
        start_port,
        end_port,
        status,
        label
    )
    VALUES (
        NEW.id,
        'udp',
        24000,
        24999,
        'active',
        'default'
    );

    INSERT INTO agent_port_ranges(
        agent_id,
        protocol,
        start_port,
        end_port,
        status,
        label
    )
    VALUES (
        NEW.id,
        'tcp',
        24000,
        24999,
        'active',
        'default'
    );
END;
