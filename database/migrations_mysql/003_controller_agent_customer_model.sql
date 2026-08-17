-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 003
-- Controller / Agent / Customer ownership model
-- =============================================================

CREATE TABLE controllers (
    id VARCHAR(191) NOT NULL,

    node_id VARCHAR(191) NOT NULL,

    name VARCHAR(255) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'active',

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_controllers_node (
        node_id
    ),

    CONSTRAINT chk_controllers_metadata_json
        CHECK (
            JSON_VALID(metadata_json)
        ),

    CONSTRAINT fk_controllers_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE agents (
    id VARCHAR(191) NOT NULL,

    controller_id VARCHAR(191) NOT NULL,
    node_id VARCHAR(191) NOT NULL,

    name VARCHAR(255) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'pending',

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_agents_node (
        node_id
    ),

    CONSTRAINT chk_agents_metadata_json
        CHECK (
            JSON_VALID(metadata_json)
        ),

    CONSTRAINT fk_agents_controller
        FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_agents_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE customers (
    id VARCHAR(191) NOT NULL,

    controller_id VARCHAR(191) NOT NULL,

    name VARCHAR(255) NOT NULL,

    email VARCHAR(320),
    phone VARCHAR(64),

    status VARCHAR(64) NOT NULL
        DEFAULT 'active',

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_customers_metadata_json
        CHECK (
            JSON_VALID(metadata_json)
        ),

    CONSTRAINT fk_customers_controller
        FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE RESTRICT
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


ALTER TABLE instances
    ADD COLUMN controller_id VARCHAR(191);

ALTER TABLE instances
    ADD COLUMN agent_id VARCHAR(191);

ALTER TABLE instances
    ADD COLUMN customer_id VARCHAR(191);


-- Existing unowned instances cannot be mapped safely.
-- This backend is currently designed for clean installation.
DELETE FROM instances;


ALTER TABLE instances
    ADD CONSTRAINT fk_instances_controller
        FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE RESTRICT;

ALTER TABLE instances
    ADD CONSTRAINT fk_instances_agent
        FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE RESTRICT;

ALTER TABLE instances
    ADD CONSTRAINT fk_instances_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers(id)
        ON DELETE RESTRICT;


DELIMITER $$

CREATE TRIGGER controllers_require_controller_node_insert
BEFORE INSERT ON controllers
FOR EACH ROW
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM nodes
        WHERE id = NEW.node_id
          AND role IN (
              'controller',
              'hybrid'
          )
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'controller_requires_controller_node';
    END IF;
END$$


CREATE TRIGGER controllers_require_controller_node_update
BEFORE UPDATE ON controllers
FOR EACH ROW
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM nodes
        WHERE id = NEW.node_id
          AND role IN (
              'controller',
              'hybrid'
          )
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'controller_requires_controller_node';
    END IF;
END$$


CREATE TRIGGER agents_require_agent_node_insert
BEFORE INSERT ON agents
FOR EACH ROW
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM nodes
        WHERE id = NEW.node_id
          AND role IN (
              'agent',
              'hybrid'
          )
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'agent_requires_agent_node';
    END IF;
END$$


CREATE TRIGGER agents_require_agent_node_update
BEFORE UPDATE ON agents
FOR EACH ROW
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM nodes
        WHERE id = NEW.node_id
          AND role IN (
              'agent',
              'hybrid'
          )
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'agent_requires_agent_node';
    END IF;
END$$


CREATE TRIGGER instances_require_ownership_insert
BEFORE INSERT ON instances
FOR EACH ROW
BEGIN
    IF (
        NEW.controller_id IS NULL
        OR NEW.agent_id IS NULL
        OR NEW.customer_id IS NULL
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'instance_requires_controller_agent_customer';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM agents
        WHERE id = NEW.agent_id
          AND controller_id = NEW.controller_id
          AND node_id = NEW.node_id
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'instance_agent_controller_mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM customers
        WHERE id = NEW.customer_id
          AND controller_id = NEW.controller_id
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'instance_customer_controller_mismatch';
    END IF;
END$$


CREATE TRIGGER instances_require_ownership_update
BEFORE UPDATE ON instances
FOR EACH ROW
BEGIN
    IF (
        NEW.controller_id IS NULL
        OR NEW.agent_id IS NULL
        OR NEW.customer_id IS NULL
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'instance_requires_controller_agent_customer';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM agents
        WHERE id = NEW.agent_id
          AND controller_id = NEW.controller_id
          AND node_id = NEW.node_id
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'instance_agent_controller_mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM customers
        WHERE id = NEW.customer_id
          AND controller_id = NEW.controller_id
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'instance_customer_controller_mismatch';
    END IF;
END$$

DELIMITER ;


CREATE INDEX idx_agents_controller
    ON agents(
        controller_id
    );

CREATE INDEX idx_customers_controller
    ON customers(
        controller_id
    );

CREATE INDEX idx_instances_ownership
    ON instances(
        controller_id,
        agent_id,
        customer_id
    );
