-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 016 - customer_account integrity parity
-- MySQL has no PostgreSQL/SQLite-style partial unique index, therefore a
-- generated nullable owner key provides the same one-owner-per-Customer rule.
-- =============================================================
ALTER TABLE customer_account_members
    ADD COLUMN owner_customer_id VARCHAR(191)
        GENERATED ALWAYS AS (
            CASE
                WHEN account_role = 'owner' THEN customer_id
                ELSE NULL
            END
        ) STORED,
    ADD UNIQUE KEY uq_customer_account_owner (owner_customer_id);
