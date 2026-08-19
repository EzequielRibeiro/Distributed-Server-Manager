-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 014
-- Customer self-service account identity and SFTP username
-- =============================================================

ALTER TABLE customers
    ADD COLUMN account_email TEXT;

ALTER TABLE customers
    ADD COLUMN sftp_username TEXT;

ALTER TABLE customers
    ADD COLUMN registration_status TEXT NOT NULL DEFAULT 'managed'
        CHECK (registration_status IN (
            'managed',
            'pending',
            'active',
            'disabled'
        ));

ALTER TABLE customers
    ADD COLUMN email_verified_at TIMESTAMPTZ;

CREATE UNIQUE INDEX idx_customers_account_email
    ON customers(LOWER(account_email))
    WHERE account_email IS NOT NULL;

CREATE UNIQUE INDEX idx_customers_sftp_username
    ON customers(sftp_username)
    WHERE sftp_username IS NOT NULL;
