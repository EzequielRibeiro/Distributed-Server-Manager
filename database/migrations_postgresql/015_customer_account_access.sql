-- Capivara Distributed Server Manager
-- Customer account members and password recovery.

CREATE TABLE customer_account_members (
    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    username TEXT NOT NULL REFERENCES dashboard_users(username) ON DELETE CASCADE,
    account_role TEXT NOT NULL DEFAULT 'member'
        CHECK (account_role IN ('owner','manager','member')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (customer_id, username)
);
CREATE UNIQUE INDEX idx_customer_account_owner ON customer_account_members(customer_id) WHERE account_role='owner';

CREATE TABLE customer_password_recovery (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES dashboard_users(username) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_customer_password_recovery_user ON customer_password_recovery(username, expires_at);
