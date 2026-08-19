-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 014
-- Customer self-service account identity and SFTP username
-- =============================================================

ALTER TABLE customers
    ADD COLUMN account_email VARCHAR(320),
    ADD COLUMN sftp_username VARCHAR(191),
    ADD COLUMN registration_status VARCHAR(32) NOT NULL DEFAULT 'managed',
    ADD COLUMN email_verified_at DATETIME(6),
    ADD CONSTRAINT chk_customers_registration_status
        CHECK (registration_status IN (
            'managed',
            'pending',
            'active',
            'disabled'
        ));

CREATE UNIQUE INDEX idx_customers_account_email
    ON customers(account_email);

CREATE UNIQUE INDEX idx_customers_sftp_username
    ON customers(sftp_username);
