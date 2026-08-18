
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 011
-- Agent managed network port ranges
-- =============================================================

CREATE TABLE agent_port_ranges (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    agent_id VARCHAR(191) NOT NULL,

    protocol VARCHAR(8) NOT NULL,

    start_port INTEGER NOT NULL,

    end_port INTEGER NOT NULL,

    status VARCHAR(16) NOT NULL
        DEFAULT 'active',

    label VARCHAR(191),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_agent_port_ranges_protocol
        CHECK (
            protocol IN (
                'tcp',
                'udp'
            )
        ),

    CONSTRAINT chk_agent_port_ranges_start
        CHECK (
            start_port BETWEEN 1 AND 65535
        ),

    CONSTRAINT chk_agent_port_ranges_end
        CHECK (
            end_port BETWEEN 1 AND 65535
        ),

    CONSTRAINT chk_agent_port_ranges_order
        CHECK (
            start_port <= end_port
        ),

    CONSTRAINT chk_agent_port_ranges_status
        CHECK (
            status IN (
                'active',
                'disabled'
            )
        ),

    CONSTRAINT fk_agent_port_ranges_agent
        FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,

    CONSTRAINT uq_agent_port_ranges
        UNIQUE (
            agent_id,
            protocol,
            start_port,
            end_port
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;

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

DELIMITER $$

CREATE TRIGGER agents_default_port_ranges_insert
AFTER INSERT ON agents
FOR EACH ROW
BEGIN
    INSERT INTO agent_port_ranges(
        agent_id,
        protocol,
        start_port,
        end_port,
        status,
        label
    )
    VALUES
        (
            NEW.id,
            'udp',
            24000,
            24999,
            'active',
            'default'
        ),
        (
            NEW.id,
            'tcp',
            24000,
            24999,
            'active',
            'default'
        );
END$$

DELIMITER ;
