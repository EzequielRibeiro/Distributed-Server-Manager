-- Capivara Distributed Server Manager
-- Customer self-service identity and account ownership.

ALTER TABLE customers
    ADD COLUMN account_email VARCHAR(320),
    ADD COLUMN sftp_username VARCHAR(32);

CREATE UNIQUE INDEX idx_customers_account_email
    ON customers(account_email);

CREATE UNIQUE INDEX idx_customers_sftp_username
    ON customers(sftp_username);
