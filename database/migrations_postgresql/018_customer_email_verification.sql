-- Capivara DSM migration 018 - one-time e-mail verification tokens
CREATE TABLE customer_email_verification (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES dashboard_users(username) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_customer_email_verification_user ON customer_email_verification(username, expires_at);
