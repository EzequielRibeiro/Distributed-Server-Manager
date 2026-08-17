-- =============================================================
-- Capivara Distributed Server Manager
-- PostgreSQL Migration 007
-- Customer identity and external billing integration
-- =============================================================

ALTER TABLE customers
    ADD COLUMN legal_name TEXT;


ALTER TABLE customers
    ADD COLUMN document_type TEXT
        CHECK (
            document_type IS NULL
            OR document_type IN (
                'cpf',
                'cnpj',
                'other'
            )
        );


ALTER TABLE customers
    ADD COLUMN document_number TEXT;


ALTER TABLE customers
    ADD COLUMN billing_provider TEXT;


ALTER TABLE customers
    ADD COLUMN billing_customer_id TEXT;


ALTER TABLE customers
    ADD COLUMN billing_status TEXT;


ALTER TABLE customers
    ADD COLUMN billing_synced_at TIMESTAMPTZ;


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
