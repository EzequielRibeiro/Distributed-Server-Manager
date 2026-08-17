-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 004
-- Instance service contracts
-- =============================================================

CREATE TABLE service_contracts (
    id VARCHAR(191) NOT NULL,
    customer_id VARCHAR(191) NOT NULL,
    game_id VARCHAR(191) NOT NULL,

    status VARCHAR(32) NOT NULL
        DEFAULT 'active',

    instance_limit INTEGER NOT NULL
        DEFAULT 1,

    starts_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    ends_at DATETIME(6),

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_service_contracts_status
        CHECK (
            status IN (
                'pending',
                'active',
                'suspended',
                'cancelled',
                'expired'
            )
        ),

    CONSTRAINT chk_service_contracts_limit
        CHECK (instance_limit > 0),

    CONSTRAINT chk_service_contracts_metadata
        CHECK (JSON_VALID(metadata_json)),

    CONSTRAINT fk_service_contracts_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers(id)
        ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE instance_contracts (
    instance_id VARCHAR(191) NOT NULL,
    contract_id VARCHAR(191) NOT NULL,

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (instance_id),

    CONSTRAINT fk_instance_contracts_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_instance_contracts_contract
        FOREIGN KEY (contract_id)
        REFERENCES service_contracts(id)
        ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


DELIMITER $$

CREATE TRIGGER instance_contract_matches_insert
BEFORE INSERT ON instance_contracts
FOR EACH ROW
BEGIN
    DECLARE contract_limit INTEGER;
    DECLARE current_count INTEGER;

    IF NOT EXISTS (
        SELECT 1
        FROM instances i
        INNER JOIN service_contracts c
            ON c.id = NEW.contract_id
        WHERE i.id = NEW.instance_id
          AND i.customer_id = c.customer_id
          AND i.game_id = c.game_id
          AND c.status = 'active'
          AND (
              c.ends_at IS NULL
              OR c.ends_at > CURRENT_TIMESTAMP(6)
          )
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
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
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'contract_instance_limit_reached';
    END IF;
END$$


CREATE TRIGGER instances_require_contract_before_active
BEFORE UPDATE ON instances
FOR EACH ROW
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
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'instance_requires_service_contract';
    END IF;
END$$

DELIMITER ;


CREATE INDEX idx_service_contracts_customer_status
    ON service_contracts(
        customer_id,
        status
    );

CREATE INDEX idx_instance_contracts_contract
    ON instance_contracts(
        contract_id
    );
