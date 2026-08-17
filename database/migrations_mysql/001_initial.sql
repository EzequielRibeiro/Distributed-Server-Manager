-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 001
-- Initial persistence model
-- =============================================================

CREATE TABLE nodes (
    id VARCHAR(191) NOT NULL,

    name VARCHAR(255) NOT NULL,

    role VARCHAR(32) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'pending',

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_nodes_role
        CHECK (
            role IN (
                'controller',
                'agent',
                'hybrid'
            )
        ),

    CONSTRAINT chk_nodes_metadata_json
        CHECK (
            JSON_VALID(metadata_json)
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE instances (
    id VARCHAR(191) NOT NULL,

    node_id VARCHAR(191),

    game_id VARCHAR(191) NOT NULL,

    edition VARCHAR(191),
    runtime_id VARCHAR(191),
    version VARCHAR(191),

    name VARCHAR(255) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'unknown',

    manifest_path TEXT,

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_instances_metadata_json
        CHECK (
            JSON_VALID(metadata_json)
        ),

    CONSTRAINT fk_instances_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE SET NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE operations (
    id VARCHAR(191) NOT NULL,

    operation_type VARCHAR(191) NOT NULL,
    status VARCHAR(64) NOT NULL,

    node_id VARCHAR(191),
    instance_id VARCHAR(191),

    request_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    result_json LONGTEXT,

    error_code VARCHAR(191),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    started_at DATETIME(6),
    completed_at DATETIME(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_operations_request_json
        CHECK (
            JSON_VALID(request_json)
        ),

    CONSTRAINT chk_operations_result_json
        CHECK (
            result_json IS NULL
            OR JSON_VALID(result_json)
        ),

    CONSTRAINT fk_operations_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_operations_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE SET NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE events (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    event_id VARCHAR(191),

    event_type VARCHAR(191) NOT NULL,

    severity VARCHAR(64) NOT NULL
        DEFAULT 'info',

    source VARCHAR(191) NOT NULL,

    node_id VARCHAR(191),
    instance_id VARCHAR(191),
    operation_id VARCHAR(191),

    payload_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_events_event_id (
        event_id
    ),

    CONSTRAINT chk_events_payload_json
        CHECK (
            JSON_VALID(payload_json)
        ),

    CONSTRAINT fk_events_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_events_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_events_operation
        FOREIGN KEY (operation_id)
        REFERENCES operations(id)
        ON DELETE SET NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE content_installations (
    instance_id VARCHAR(191) NOT NULL,
    content_id VARCHAR(191) NOT NULL,

    content_type VARCHAR(191) NOT NULL,
    version VARCHAR(191) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'installed',

    lock_path TEXT,

    installed_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        instance_id,
        content_id
    ),

    CONSTRAINT fk_content_installations_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_instances_node_game
    ON instances(
        node_id,
        game_id
    );

CREATE INDEX idx_operations_status_created
    ON operations(
        status,
        created_at
    );

CREATE INDEX idx_events_created
    ON events(
        created_at
    );

CREATE INDEX idx_events_instance_created
    ON events(
        instance_id,
        created_at
    );

CREATE INDEX idx_content_instance_status
    ON content_installations(
        instance_id,
        status
    );
