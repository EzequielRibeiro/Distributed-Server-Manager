-- Capivara DSM - Migration 026 - PostgreSQL
-- Preconfiguration attached to an Agent installation before enrollment.
-- 025 is intentionally reserved by the open Agent game-data orchestration work.

CREATE TABLE agent_installation_preconfiguration (
    installation_id TEXT PRIMARY KEY
        REFERENCES agent_pairing_tokens(id) ON DELETE CASCADE,
    requested_name TEXT,
    port_protocol TEXT
        CHECK (port_protocol IN ('tcp','udp','both')),
    port_start INTEGER,
    port_end INTEGER,
    applied_at TIMESTAMPTZ,
    apply_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (port_start IS NULL AND port_end IS NULL AND port_protocol IS NULL)
        OR
        (port_start BETWEEN 1 AND 65535
         AND port_end BETWEEN port_start AND 65535
         AND port_protocol IS NOT NULL)
    )
);

CREATE INDEX idx_agent_install_preconfig_applied
    ON agent_installation_preconfiguration(applied_at, apply_error);
