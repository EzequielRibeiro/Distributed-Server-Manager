-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 017 - per-login e-mail identity and team invitations
-- =============================================================
CREATE TABLE customer_user_identities (
    username TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    email_verified_at TEXT,
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);
CREATE UNIQUE INDEX idx_customer_user_identity_email
    ON customer_user_identities(LOWER(email));

CREATE TABLE customer_invitations (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    email TEXT NOT NULL,
    account_role TEXT NOT NULL CHECK (account_role IN ('manager','member')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    revoked_at TEXT,
    invited_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (invited_by) REFERENCES dashboard_users(username) ON DELETE RESTRICT
);
CREATE INDEX idx_customer_invitations_customer
    ON customer_invitations(customer_id, created_at);
CREATE INDEX idx_customer_invitations_email
    ON customer_invitations(email, expires_at);

CREATE TABLE customer_invitation_access (
    invitation_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    permission_profile TEXT NOT NULL CHECK (permission_profile IN ('viewer','operator','manager')),
    PRIMARY KEY (invitation_id, instance_id),
    FOREIGN KEY (invitation_id) REFERENCES customer_invitations(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
