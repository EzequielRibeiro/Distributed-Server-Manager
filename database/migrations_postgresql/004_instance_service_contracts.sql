-- =============================================================
-- Capivara Distributed Server Manager
-- PostgreSQL Migration 004
-- Instance service contracts
-- =============================================================

CREATE TABLE service_contracts (
    id TEXT PRIMARY KEY,

    customer_id TEXT NOT NULL,
    game_id TEXT NOT NULL,

    status TEXT NOT NULL
        DEFAULT 'active'
        CHECK (
            status IN (
                'pending',
                'active',
                'suspended',
                'cancelled',
                'expired'
            )
        ),

    instance_limit INTEGER NOT NULL
        DEFAULT 1
        CHECK (instance_limit > 0),

    starts_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    ends_at TIMESTAMPTZ,

    metadata_json JSONB NOT NULL
        DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_service_contracts_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers(id)
        ON DELETE RESTRICT
);


CREATE TABLE instance_contracts (
    instance_id TEXT PRIMARY KEY,

    contract_id TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_instance_contracts_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_instance_contracts_contract
        FOREIGN KEY (contract_id)
        REFERENCES service_contracts(id)
        ON DELETE RESTRICT
);


-- =============================================================
-- Contract validation
-- =============================================================

CREATE OR REPLACE FUNCTION
validate_instance_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    contract_limit INTEGER;
    current_count INTEGER;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM instances i
        JOIN service_contracts c
          ON c.id = NEW.contract_id
        WHERE i.id = NEW.instance_id
          AND i.customer_id = c.customer_id
          AND i.game_id = c.game_id
          AND c.status = 'active'
          AND (
              c.ends_at IS NULL
              OR c.ends_at > CURRENT_TIMESTAMP
          )
    ) THEN
        RAISE EXCEPTION
            'instance_contract_mismatch';
    END IF;

    SELECT instance_limit
    INTO contract_limit
    FROM service_contracts
    WHERE id = NEW.contract_id;

    SELECT COUNT(*)
    INTO current_count
    FROM instance_contracts
    WHERE contract_id = NEW.contract_id;

    IF current_count >= contract_limit THEN
        RAISE EXCEPTION
            'contract_instance_limit_reached';
    END IF;

    RETURN NEW;
END;
$$;


CREATE TRIGGER instance_contract_matches_insert
BEFORE INSERT
ON instance_contracts
FOR EACH ROW
EXECUTE FUNCTION validate_instance_contract();


-- =============================================================
-- Active instance requires contract
-- =============================================================

CREATE OR REPLACE FUNCTION
validate_instance_requires_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status NOT IN (
        'pending',
        'provisioning'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM instance_contracts
        WHERE instance_id = NEW.id
    )
    THEN
        RAISE EXCEPTION
            'instance_requires_service_contract';
    END IF;

    RETURN NEW;
END;
$$;


CREATE TRIGGER instances_require_contract_before_active
BEFORE UPDATE OF status
ON instances
FOR EACH ROW
EXECUTE FUNCTION validate_instance_requires_contract();


CREATE INDEX idx_service_contracts_customer_status
    ON service_contracts(
        customer_id,
        status
    );

CREATE INDEX idx_instance_contracts_contract
    ON instance_contracts(
        contract_id
    );
