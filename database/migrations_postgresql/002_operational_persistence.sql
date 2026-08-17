-- =============================================================
-- Capivara Distributed Server Manager
-- PostgreSQL Migration 002
-- Operational persistence
-- =============================================================

CREATE TABLE state_imports (
    source_path TEXT PRIMARY KEY,

    source_kind TEXT NOT NULL,
    checksum TEXT NOT NULL,

    records_imported INTEGER NOT NULL
        DEFAULT 0
        CHECK (records_imported >= 0),

    source_updated_at TIMESTAMPTZ,

    imported_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);


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
