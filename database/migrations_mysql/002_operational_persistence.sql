-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 002
-- Operational persistence
-- =============================================================

CREATE TABLE state_imports (
    source_path VARCHAR(512) NOT NULL,

    source_kind VARCHAR(191) NOT NULL,

    checksum CHAR(64) NOT NULL,

    records_imported INTEGER NOT NULL
        DEFAULT 0,

    source_updated_at DATETIME(6),

    imported_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        source_path
    ),

    CONSTRAINT chk_state_imports_records
        CHECK (
            records_imported >= 0
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_events_type_created
    ON events(
        event_type,
        created_at
    );

CREATE INDEX idx_events_severity_created
    ON events(
        severity,
        created_at
    );

CREATE INDEX idx_operations_type_created
    ON operations(
        operation_type,
        created_at
    );

CREATE INDEX idx_operations_instance_created
    ON operations(
        instance_id,
        created_at
    );

CREATE INDEX idx_state_imports_kind_imported
    ON state_imports(
        source_kind,
        imported_at
    );
