-- Capivara DSM - Migration 026 - MySQL/MariaDB
-- Preconfiguration attached to an Agent installation before enrollment.
-- 025 is intentionally reserved by the open Agent game-data orchestration work.

CREATE TABLE agent_installation_preconfiguration (
    installation_id VARCHAR(191) PRIMARY KEY,
    requested_name VARCHAR(128),
    port_protocol VARCHAR(8),
    port_start INTEGER,
    port_end INTEGER,
    applied_at TIMESTAMP(6) NULL,
    apply_error TEXT,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_install_preconfig_installation
        FOREIGN KEY (installation_id)
        REFERENCES agent_pairing_tokens(id)
        ON DELETE CASCADE,
    CONSTRAINT chk_agent_install_preconfig_protocol
        CHECK (port_protocol IN ('tcp','udp','both') OR port_protocol IS NULL),
    CONSTRAINT chk_agent_install_preconfig_range
        CHECK (
            (port_start IS NULL AND port_end IS NULL AND port_protocol IS NULL)
            OR
            (port_start BETWEEN 1 AND 65535
             AND port_end BETWEEN port_start AND 65535
             AND port_protocol IS NOT NULL)
        )
);

CREATE INDEX idx_agent_install_preconfig_applied
    ON agent_installation_preconfiguration(applied_at, apply_error(191));
