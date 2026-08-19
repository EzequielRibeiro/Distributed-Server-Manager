-- Capivara Distributed Server Manager
-- Customer self-service identity and account ownership.

ALTER TABLE customers ADD COLUMN account_email TEXT;
ALTER TABLE customers ADD COLUMN sftp_username TEXT;

CREATE UNIQUE INDEX idx_customers_account_email
    ON customers(LOWER(account_email))
    WHERE account_email IS NOT NULL;

CREATE UNIQUE INDEX idx_customers_sftp_username
    ON customers(sftp_username)
    WHERE sftp_username IS NOT NULL;
