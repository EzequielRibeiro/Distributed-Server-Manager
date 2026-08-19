-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 018 - one-time e-mail verification tokens
-- =============================================================
CREATE TABLE customer_email_verification (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);
CREATE INDEX idx_customer_email_verification_user
    ON customer_email_verification(username, expires_at);
