-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 009
-- Instance network port reservations
-- =============================================================

CREATE TABLE instance_ports (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    instance_id VARCHAR(191) NOT NULL,
    node_id VARCHAR(191) NOT NULL,

    name VARCHAR(191) NOT NULL,

    protocol VARCHAR(8) NOT NULL,

    port INTEGER NOT NULL,

    bind_address VARCHAR(191) NOT NULL
        DEFAULT '0.0.0.0',

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_instance_ports_protocol
        CHECK (
            protocol IN (
                'tcp',
                'udp'
            )
        ),

    CONSTRAINT chk_instance_ports_port
        CHECK (
            port BETWEEN 1 AND 65535
        ),

    CONSTRAINT fk_instance_ports_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_instance_ports_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE CASCADE,

    CONSTRAINT uq_instance_ports_instance_name_protocol
        UNIQUE (
            instance_id,
            name,
            protocol
        ),

    CONSTRAINT uq_instance_ports_node_protocol_port
        UNIQUE (
            node_id,
            protocol,
            port
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_instance_ports_instance
    ON instance_ports(instance_id);

CREATE INDEX idx_instance_ports_node
    ON instance_ports(node_id);

CREATE INDEX idx_instance_ports_node_protocol_port
    ON instance_ports(
        node_id,
        protocol,
        port
    );
