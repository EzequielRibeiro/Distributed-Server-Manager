-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 015
-- Customer account members and password recovery
-- =============================================================

CREATE TABLE customer_account_members (
    customer_id TEXT NOT NULL,
    username TEXT NOT NULL,
    account_role TEXT NOT NULL DEFAULT 'member'
        CHECK (account_role IN ('owner','manager','member')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (customer_id, username),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_customer_account_owner
    ON customer_account_members(customer_id)
    WHERE account_role='owner';

CREATE TABLE customer_password_recovery (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);

CREATE INDEX idx_customer_password_recovery_user
    ON customer_password_recovery(username, expires_at);
