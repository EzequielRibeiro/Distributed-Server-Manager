-- Capivara DSM migration 017 - per-login e-mail identity and invitations
CREATE TABLE customer_user_identities (
    username TEXT PRIMARY KEY REFERENCES dashboard_users(username) ON DELETE CASCADE,
    email TEXT NOT NULL,
    email_verified_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX idx_customer_user_identity_email
    ON customer_user_identities(LOWER(email));

CREATE TABLE customer_invitations (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    account_role TEXT NOT NULL CHECK (account_role IN ('manager','member')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    invited_by TEXT NOT NULL REFERENCES dashboard_users(username) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_customer_invitations_customer ON customer_invitations(customer_id, created_at);
CREATE INDEX idx_customer_invitations_email ON customer_invitations(email, expires_at);

CREATE TABLE customer_invitation_access (
    invitation_id TEXT NOT NULL REFERENCES customer_invitations(id) ON DELETE CASCADE,
    instance_id TEXT NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    permission_profile TEXT NOT NULL CHECK (permission_profile IN ('viewer','operator','manager')),
    PRIMARY KEY (invitation_id, instance_id)
);
