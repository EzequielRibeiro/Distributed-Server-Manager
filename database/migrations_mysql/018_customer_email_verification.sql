-- Capivara DSM MySQL migration 018 - one-time e-mail verification tokens
CREATE TABLE customer_email_verification (
    id VARCHAR(191) NOT NULL,
    username VARCHAR(191) NOT NULL,
    token_hash CHAR(64) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    consumed_at DATETIME(6),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_customer_email_verification_token (token_hash),
    CONSTRAINT fk_customer_email_verification_user FOREIGN KEY (username)
        REFERENCES dashboard_users(username) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_customer_email_verification_user ON customer_email_verification(username, expires_at);
