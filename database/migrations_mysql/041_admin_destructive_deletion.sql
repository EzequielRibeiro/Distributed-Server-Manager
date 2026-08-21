-- Capivara DSM - Migration 041 - MySQL/MariaDB
-- Add explicit transitional contract deletion state and Agent runtime remove action.

CREATE TABLE service_contracts_v2 (
    id VARCHAR(191) NOT NULL,
    customer_id VARCHAR(191) NOT NULL,
    game_id VARCHAR(191) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    instance_limit INTEGER NOT NULL DEFAULT 1,
    starts_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ends_at DATETIME(6),
    metadata_json LONGTEXT NOT NULL DEFAULT ('{}'),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT chk_service_contracts_v2_status CHECK (
        status IN ('pending','active','suspended','cancelled','expired','deleting')
    ),
    CONSTRAINT chk_service_contracts_v2_limit CHECK (instance_limit > 0),
    CONSTRAINT chk_service_contracts_v2_metadata CHECK (JSON_VALID(metadata_json)),
    CONSTRAINT fk_service_contracts_v2_customer FOREIGN KEY (customer_id)
        REFERENCES customers(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE instance_contracts_v2 (
    instance_id VARCHAR(191) NOT NULL,
    contract_id VARCHAR(191) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (instance_id),
    CONSTRAINT fk_instance_contracts_v2_instance FOREIGN KEY (instance_id)
        REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT fk_instance_contracts_v2_contract FOREIGN KEY (contract_id)
        REFERENCES service_contracts_v2(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO service_contracts_v2
(id,customer_id,game_id,status,instance_limit,starts_at,ends_at,metadata_json,created_at,updated_at)
SELECT id,customer_id,game_id,status,instance_limit,starts_at,ends_at,metadata_json,created_at,updated_at
FROM service_contracts;

INSERT INTO instance_contracts_v2(instance_id,contract_id,created_at)
SELECT instance_id,contract_id,created_at
FROM instance_contracts;

DROP TRIGGER IF EXISTS instance_contract_matches_insert;
DROP TRIGGER IF EXISTS instances_require_contract_before_active;
DROP TABLE instance_contracts;
DROP TABLE service_contracts;
RENAME TABLE service_contracts_v2 TO service_contracts,
             instance_contracts_v2 TO instance_contracts;

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
        INNER JOIN service_contracts c ON c.id = NEW.contract_id
        WHERE i.id = NEW.instance_id
          AND i.customer_id = c.customer_id
          AND i.game_id = c.game_id
          AND c.status = 'active'
          AND (c.ends_at IS NULL OR c.ends_at > CURRENT_TIMESTAMP(6))
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'instance_contract_mismatch';
    END IF;

    SELECT instance_limit INTO contract_limit
    FROM service_contracts WHERE id = NEW.contract_id;

    SELECT COUNT(*) INTO current_count
    FROM instance_contracts WHERE contract_id = NEW.contract_id;

    IF current_count >= contract_limit THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'contract_instance_limit_reached';
    END IF;
END$$

CREATE TRIGGER instances_require_contract_before_active
BEFORE UPDATE ON instances
FOR EACH ROW
BEGIN
    IF NEW.status NOT IN ('pending','provisioning','deleting')
       AND NOT EXISTS (
           SELECT 1 FROM instance_contracts WHERE instance_id = NEW.id
       ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'instance_requires_service_contract';
    END IF;
END$$

DELIMITER ;

CREATE INDEX idx_service_contracts_customer_status
    ON service_contracts(customer_id,status);
CREATE INDEX idx_instance_contracts_contract
    ON instance_contracts(contract_id);

CREATE TABLE agent_instance_commands_v3 (
    command_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NOT NULL,
    action VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    requested_by VARCHAR(191),
    result_json LONGTEXT,
    last_error TEXT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_instance_commands_v3_agent FOREIGN KEY (agent_id)
        REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_commands_v3_instance FOREIGN KEY (instance_id)
        REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_commands_v3_action CHECK (
        action IN ('status','doctor','start','stop','restart','remove')
    ),
    CONSTRAINT chk_agent_instance_commands_v3_status CHECK (
        status IN ('queued','delivered','completed','failed')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO agent_instance_commands_v3
(command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at)
SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at
FROM agent_instance_commands;

DROP TABLE agent_instance_commands;
RENAME TABLE agent_instance_commands_v3 TO agent_instance_commands;

CREATE INDEX idx_agent_instance_commands_agent_status
    ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance
    ON agent_instance_commands(instance_id,created_at);
