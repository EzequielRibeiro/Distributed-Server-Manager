-- Capivara Distributed Server Manager
-- Customer account members and password recovery.

CREATE TABLE customer_account_members (
    customer_id VARCHAR(191) NOT NULL,
    username VARCHAR(191) NOT NULL,
    account_role VARCHAR(32) NOT NULL DEFAULT 'member',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (customer_id, username),
    CONSTRAINT chk_customer_account_role CHECK (account_role IN ('owner','manager','member')),
    CONSTRAINT fk_customer_account_member_customer FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    CONSTRAINT fk_customer_account_member_user FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_customer_account_member_role ON customer_account_members(customer_id, account_role);

CREATE TABLE customer_password_recovery (
    id VARCHAR(191) NOT NULL,
    username VARCHAR(191) NOT NULL,
    token_hash CHAR(64) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    consumed_at DATETIME(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_customer_password_recovery_token (token_hash),
    CONSTRAINT fk_customer_password_recovery_user FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_customer_password_recovery_user ON customer_password_recovery(username, expires_at);
