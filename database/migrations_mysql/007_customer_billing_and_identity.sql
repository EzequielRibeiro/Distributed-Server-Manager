-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 007
-- Customer identity and external billing
-- =============================================================

ALTER TABLE customers
    ADD COLUMN legal_name VARCHAR(255);


ALTER TABLE customers
    ADD COLUMN document_type VARCHAR(32);


ALTER TABLE customers
    ADD COLUMN document_number VARCHAR(191);


ALTER TABLE customers
    ADD COLUMN billing_provider VARCHAR(191);


ALTER TABLE customers
    ADD COLUMN billing_customer_id VARCHAR(191);


ALTER TABLE customers
    ADD COLUMN billing_status VARCHAR(64);


ALTER TABLE customers
    ADD COLUMN billing_synced_at DATETIME(6);


ALTER TABLE customers
    ADD CONSTRAINT chk_customers_document_type
        CHECK (
            document_type IS NULL
            OR document_type IN (
                'cpf',
                'cnpj',
                'other'
            )
        );


CREATE INDEX idx_customers_document
    ON customers(
        document_type,
        document_number
    );


CREATE INDEX idx_customers_billing
    ON customers(
        billing_provider,
        billing_customer_id
    );


CREATE INDEX idx_customers_billing_status
    ON customers(
        billing_status
    );
