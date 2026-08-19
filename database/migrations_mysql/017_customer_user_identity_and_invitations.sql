-- Capivara DSM MySQL migration 017 - per-login e-mail identity and invitations
CREATE TABLE customer_user_identities (
    username VARCHAR(191) NOT NULL,
    email VARCHAR(320) NOT NULL,
    email_verified_at DATETIME(6),
    PRIMARY KEY (username),
    UNIQUE KEY uq_customer_user_identity_email (email),
    CONSTRAINT fk_customer_user_identity_user FOREIGN KEY (username)
        REFERENCES dashboard_users(username) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO customer_user_identities(username,email,email_verified_at)
SELECT m.username,c.account_email,c.email_verified_at
FROM customer_account_members m
JOIN customers c ON c.id=m.customer_id
WHERE m.account_role='owner'
  AND c.account_email IS NOT NULL;

CREATE TABLE customer_invitations (
    id VARCHAR(191) NOT NULL,
    customer_id VARCHAR(191) NOT NULL,
    email VARCHAR(320) NOT NULL,
    account_role VARCHAR(32) NOT NULL,
    token_hash CHAR(64) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    accepted_at DATETIME(6),
    revoked_at DATETIME(6),
    invited_by VARCHAR(191) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_customer_invitations_token (token_hash),
    CONSTRAINT chk_customer_invitation_role CHECK (account_role IN ('manager','member')),
    CONSTRAINT fk_customer_invitation_customer FOREIGN KEY (customer_id)
        REFERENCES customers(id) ON DELETE CASCADE,
    CONSTRAINT fk_customer_invitation_actor FOREIGN KEY (invited_by)
        REFERENCES dashboard_users(username) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_customer_invitations_customer ON customer_invitations(customer_id, created_at);
CREATE INDEX idx_customer_invitations_email ON customer_invitations(email, expires_at);

CREATE TABLE customer_invitation_access (
    invitation_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NOT NULL,
    permission_profile VARCHAR(32) NOT NULL,
    PRIMARY KEY (invitation_id, instance_id),
    CONSTRAINT chk_customer_invitation_access_profile CHECK (permission_profile IN ('viewer','operator','manager')),
    CONSTRAINT fk_customer_invitation_access_invite FOREIGN KEY (invitation_id)
        REFERENCES customer_invitations(id) ON DELETE CASCADE,
    CONSTRAINT fk_customer_invitation_access_instance FOREIGN KEY (instance_id)
        REFERENCES instances(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
