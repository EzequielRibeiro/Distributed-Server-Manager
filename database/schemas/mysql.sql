-- Capivara DSM complete schema v41 - new installations only
-- source: 001_initial.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 001
-- Initial persistence model
-- =============================================================

CREATE TABLE nodes (
    id VARCHAR(191) NOT NULL,

    name VARCHAR(255) NOT NULL,

    role VARCHAR(32) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'pending',

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_nodes_role
        CHECK (
            role IN (
                'controller',
                'agent',
                'hybrid'
            )
        ),

    CONSTRAINT chk_nodes_metadata_json
        CHECK (
            JSON_VALID(metadata_json)
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE instances (
    id VARCHAR(191) NOT NULL,

    node_id VARCHAR(191),

    game_id VARCHAR(191) NOT NULL,

    edition VARCHAR(191),
    runtime_id VARCHAR(191),
    version VARCHAR(191),

    name VARCHAR(255) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'unknown',

    manifest_path TEXT,

    metadata_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_instances_metadata_json
        CHECK (
            JSON_VALID(metadata_json)
        ),

    CONSTRAINT fk_instances_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE SET NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE operations (
    id VARCHAR(191) NOT NULL,

    operation_type VARCHAR(191) NOT NULL,
    status VARCHAR(64) NOT NULL,

    node_id VARCHAR(191),
    instance_id VARCHAR(191),

    request_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    result_json LONGTEXT,

    error_code VARCHAR(191),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    started_at DATETIME(6),
    completed_at DATETIME(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_operations_request_json
        CHECK (
            JSON_VALID(request_json)
        ),

    CONSTRAINT chk_operations_result_json
        CHECK (
            result_json IS NULL
            OR JSON_VALID(result_json)
        ),

    CONSTRAINT fk_operations_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_operations_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE SET NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE events (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    event_id VARCHAR(191),

    event_type VARCHAR(191) NOT NULL,

    severity VARCHAR(64) NOT NULL
        DEFAULT 'info',

    source VARCHAR(191) NOT NULL,

    node_id VARCHAR(191),
    instance_id VARCHAR(191),
    operation_id VARCHAR(191),

    payload_json LONGTEXT NOT NULL
        DEFAULT ('{}'),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    UNIQUE KEY uq_events_event_id (
        event_id
    ),

    CONSTRAINT chk_events_payload_json
        CHECK (
            JSON_VALID(payload_json)
        ),

    CONSTRAINT fk_events_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_events_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_events_operation
        FOREIGN KEY (operation_id)
        REFERENCES operations(id)
        ON DELETE SET NULL
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE content_installations (
    instance_id VARCHAR(191) NOT NULL,
    content_id VARCHAR(191) NOT NULL,

    content_type VARCHAR(191) NOT NULL,
    version VARCHAR(191) NOT NULL,

    status VARCHAR(64) NOT NULL
        DEFAULT 'installed',

    lock_path TEXT,

    installed_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        instance_id,
        content_id
    ),

    CONSTRAINT fk_content_installations_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_instances_node_game
    ON instances(
        node_id,
        game_id
    );

CREATE INDEX idx_operations_status_created
    ON operations(
        status,
        created_at
    );

CREATE INDEX idx_events_created
    ON events(
        created_at
    );

CREATE INDEX idx_events_instance_created
    ON events(
        instance_id,
        created_at
    );

CREATE INDEX idx_content_instance_status
    ON content_installations(
        instance_id,
        status
    );

-- source: 002_operational_persistence.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 002
-- Operational persistence
-- =============================================================

CREATE TABLE state_imports (
    source_path VARCHAR(512) NOT NULL,

    source_kind VARCHAR(191) NOT NULL,

    checksum CHAR(64) NOT NULL,

    records_imported INTEGER NOT NULL
        DEFAULT 0,

    source_updated_at DATETIME(6),

    imported_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        source_path
    ),

    CONSTRAINT chk_state_imports_records
        CHECK (
            records_imported >= 0
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_events_type_created
    ON events(
        event_type,
        created_at
    );

CREATE INDEX idx_events_severity_created
    ON events(
        severity,
        created_at
    );

CREATE INDEX idx_operations_type_created
    ON operations(
        operation_type,
        created_at
    );

CREATE INDEX idx_operations_instance_created
    ON operations(
        instance_id,
        created_at
    );

CREATE INDEX idx_state_imports_kind_imported
    ON state_imports(
        source_kind,
        imported_at
    );

-- source: 003_controller_agent_customer_model.sql
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

-- source: 004_instance_service_contracts.sql
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

-- source: 005_dashboard_users.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 005
-- Dashboard users, permissions and audit
-- =============================================================

CREATE TABLE dashboard_users (
    username VARCHAR(191) NOT NULL,

    password_hash VARCHAR(512) NOT NULL,

    role VARCHAR(32) NOT NULL,

    scope_id VARCHAR(191),

    active BOOLEAN NOT NULL
        DEFAULT TRUE,

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (username),

    CONSTRAINT chk_dashboard_users_role
        CHECK (
            role IN (
                'admin',
                'controller',
                'customer',
                'operator'
            )
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE instance_access (
    username VARCHAR(191) NOT NULL,

    instance_id VARCHAR(191) NOT NULL,

    permission_profile VARCHAR(32) NOT NULL
        DEFAULT 'viewer',

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (
        username,
        instance_id
    ),

    CONSTRAINT chk_instance_access_profile
        CHECK (
            permission_profile IN (
                'viewer',
                'operator',
                'manager'
            )
        ),

    CONSTRAINT fk_instance_access_user
        FOREIGN KEY (username)
        REFERENCES dashboard_users(username)
        ON DELETE CASCADE,

    CONSTRAINT fk_instance_access_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE TABLE audit_log (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    username VARCHAR(191) NOT NULL,

    instance_id VARCHAR(191),

    action VARCHAR(191) NOT NULL,

    result VARCHAR(191) NOT NULL,

    details LONGTEXT,

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_dashboard_users_role_scope
    ON dashboard_users(
        role,
        scope_id,
        active
    );

CREATE INDEX idx_audit_log_instance_created
    ON audit_log(
        instance_id,
        created_at
    );

-- source: 006_customer_administration.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 006
-- Customer administration
--
-- Historical migration intentionally contains no schema changes.
-- =============================================================

-- source: 007_customer_billing_and_identity.sql
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

-- source: 008_instance_runtime_selection.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 008
-- Instance runtime selection metadata
-- =============================================================

ALTER TABLE instances
    ADD COLUMN variant VARCHAR(191);

ALTER TABLE instances
    ADD COLUMN game_version VARCHAR(191);

ALTER TABLE instances
    ADD COLUMN build_id VARCHAR(191);

-- source: 009_instance_network_ports.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 009
-- Instance network port reservations
-- =============================================================

CREATE TABLE instance_ports (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    instance_id VARCHAR(191) NOT NULL,
    node_id VARCHAR(191) NOT NULL,

    name VARCHAR(191) NOT NULL,

    protocol VARCHAR(8) NOT NULL,

    port INTEGER NOT NULL,

    bind_address VARCHAR(191) NOT NULL
        DEFAULT '0.0.0.0',

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_instance_ports_protocol
        CHECK (
            protocol IN (
                'tcp',
                'udp'
            )
        ),

    CONSTRAINT chk_instance_ports_port
        CHECK (
            port BETWEEN 1 AND 65535
        ),

    CONSTRAINT fk_instance_ports_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_instance_ports_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE CASCADE,

    CONSTRAINT uq_instance_ports_instance_name_protocol
        UNIQUE (
            instance_id,
            name,
            protocol
        ),

    CONSTRAINT uq_instance_ports_node_protocol_port
        UNIQUE (
            node_id,
            protocol,
            port
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


CREATE INDEX idx_instance_ports_instance
    ON instance_ports(instance_id);

CREATE INDEX idx_instance_ports_node
    ON instance_ports(node_id);

CREATE INDEX idx_instance_ports_node_protocol_port
    ON instance_ports(
        node_id,
        protocol,
        port
    );

-- source: 010_alert_persistence.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 010
-- Alert persistence
-- =============================================================


-- =============================================================
-- ALERTS
-- =============================================================

CREATE TABLE alerts (
    id VARCHAR(191) NOT NULL,

    scope VARCHAR(32) NOT NULL,

    controller_id VARCHAR(191),
    agent_id VARCHAR(191),
    node_id VARCHAR(191),
    instance_id VARCHAR(191),

    rule_id VARCHAR(191) NOT NULL,

    level VARCHAR(32) NOT NULL,

    state VARCHAR(32) NOT NULL,

    message LONGTEXT NOT NULL,

    opened_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    acknowledged_at DATETIME(6),
    resolved_at DATETIME(6),
    suppressed_until DATETIME(6),


    -- ---------------------------------------------------------
    -- Active-alert deduplication columns.
    --
    -- For active alerts these hold binary representations of
    -- the logical key. For RESOLVED alerts they become NULL.
    --
    -- VARBINARY avoids utf8mb4 index expansion and keeps the
    -- composite unique index comfortably inside InnoDB limits.
    -- ---------------------------------------------------------

    active_scope VARBINARY(32)
        GENERATED ALWAYS AS (
            CASE
                WHEN state <> 'RESOLVED'
                THEN CONVERT(scope USING binary)
                ELSE NULL
            END
        ) STORED,

    active_rule_id VARBINARY(191)
        GENERATED ALWAYS AS (
            CASE
                WHEN state <> 'RESOLVED'
                THEN CONVERT(rule_id USING binary)
                ELSE NULL
            END
        ) STORED,

    active_controller_id VARBINARY(191)
        GENERATED ALWAYS AS (
            CASE
                WHEN state <> 'RESOLVED'
                THEN CONVERT(
                    COALESCE(controller_id, '')
                    USING binary
                )
                ELSE NULL
            END
        ) STORED,

    active_agent_id VARBINARY(191)
        GENERATED ALWAYS AS (
            CASE
                WHEN state <> 'RESOLVED'
                THEN CONVERT(
                    COALESCE(agent_id, '')
                    USING binary
                )
                ELSE NULL
            END
        ) STORED,

    active_node_id VARBINARY(191)
        GENERATED ALWAYS AS (
            CASE
                WHEN state <> 'RESOLVED'
                THEN CONVERT(
                    COALESCE(node_id, '')
                    USING binary
                )
                ELSE NULL
            END
        ) STORED,

    active_instance_id VARBINARY(191)
        GENERATED ALWAYS AS (
            CASE
                WHEN state <> 'RESOLVED'
                THEN CONVERT(
                    COALESCE(instance_id, '')
                    USING binary
                )
                ELSE NULL
            END
        ) STORED,


    PRIMARY KEY (id),


    CONSTRAINT chk_alerts_scope
        CHECK (
            scope IN (
                'controller',
                'agent',
                'node',
                'instance'
            )
        ),


    CONSTRAINT chk_alerts_level
        CHECK (
            level IN (
                'INFO',
                'WARNING',
                'CRITICAL'
            )
        ),


    CONSTRAINT chk_alerts_state
        CHECK (
            state IN (
                'OPEN',
                'ACKNOWLEDGED',
                'RESOLVED',
                'SUPPRESSED'
            )
        ),


    CONSTRAINT fk_alerts_controller
        FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE RESTRICT,


    CONSTRAINT fk_alerts_agent
        FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE RESTRICT,


    CONSTRAINT fk_alerts_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE RESTRICT,


    CONSTRAINT fk_alerts_instance
        FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE RESTRICT,


    CONSTRAINT uq_alerts_active_target
        UNIQUE (
            active_scope,
            active_rule_id,
            active_controller_id,
            active_agent_id,
            active_node_id,
            active_instance_id
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


-- =============================================================
-- ALERT EVENTS
-- =============================================================

CREATE TABLE alert_events (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    alert_id VARCHAR(191) NOT NULL,

    action VARCHAR(32) NOT NULL,

    level VARCHAR(32) NOT NULL,

    old_state VARCHAR(32),

    new_state VARCHAR(32) NOT NULL,

    message LONGTEXT NOT NULL,

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),


    CONSTRAINT chk_alert_events_action
        CHECK (
            action IN (
                'OPEN',
                'REOPEN',
                'ESCALATE',
                'ACK',
                'RESOLVE',
                'SUPPRESS'
            )
        ),


    CONSTRAINT chk_alert_events_level
        CHECK (
            level IN (
                'INFO',
                'WARNING',
                'CRITICAL'
            )
        ),


    CONSTRAINT chk_alert_events_old_state
        CHECK (
            old_state IS NULL
            OR old_state IN (
                'OPEN',
                'ACKNOWLEDGED',
                'RESOLVED',
                'SUPPRESSED'
            )
        ),


    CONSTRAINT chk_alert_events_new_state
        CHECK (
            new_state IN (
                'OPEN',
                'ACKNOWLEDGED',
                'RESOLVED',
                'SUPPRESSED'
            )
        ),


    CONSTRAINT fk_alert_events_alert
        FOREIGN KEY (alert_id)
        REFERENCES alerts(id)
        ON DELETE CASCADE
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;


-- =============================================================
-- ALERT SCOPE INTEGRITY
-- =============================================================

DELIMITER $$


CREATE TRIGGER alerts_validate_scope_insert
BEFORE INSERT ON alerts
FOR EACH ROW
BEGIN

    IF NEW.scope = 'controller'
       AND NEW.controller_id IS NULL
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_controller_scope_requires_controller';
    END IF;


    IF NEW.scope = 'agent'
       AND (
           NEW.controller_id IS NULL
           OR NEW.agent_id IS NULL
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_agent_scope_requires_controller_agent';
    END IF;


    IF NEW.scope = 'node'
       AND (
           NEW.controller_id IS NULL
           OR NEW.node_id IS NULL
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_node_scope_requires_controller_node';
    END IF;


    IF NEW.scope = 'instance'
       AND (
           NEW.controller_id IS NULL
           OR NEW.agent_id IS NULL
           OR NEW.node_id IS NULL
           OR NEW.instance_id IS NULL
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_instance_scope_requires_controller_agent_node_instance';
    END IF;


    IF NEW.agent_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM agents
           WHERE id = NEW.agent_id
             AND controller_id = NEW.controller_id
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_agent_controller_mismatch';
    END IF;


    IF NEW.instance_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM instances
           WHERE id = NEW.instance_id
             AND controller_id = NEW.controller_id
             AND agent_id = NEW.agent_id
             AND node_id = NEW.node_id
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_instance_ownership_mismatch';
    END IF;

END$$


CREATE TRIGGER alerts_validate_scope_update
BEFORE UPDATE ON alerts
FOR EACH ROW
BEGIN

    IF NEW.scope = 'controller'
       AND NEW.controller_id IS NULL
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_controller_scope_requires_controller';
    END IF;


    IF NEW.scope = 'agent'
       AND (
           NEW.controller_id IS NULL
           OR NEW.agent_id IS NULL
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_agent_scope_requires_controller_agent';
    END IF;


    IF NEW.scope = 'node'
       AND (
           NEW.controller_id IS NULL
           OR NEW.node_id IS NULL
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_node_scope_requires_controller_node';
    END IF;


    IF NEW.scope = 'instance'
       AND (
           NEW.controller_id IS NULL
           OR NEW.agent_id IS NULL
           OR NEW.node_id IS NULL
           OR NEW.instance_id IS NULL
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_instance_scope_requires_controller_agent_node_instance';
    END IF;


    IF NEW.agent_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM agents
           WHERE id = NEW.agent_id
             AND controller_id = NEW.controller_id
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_agent_controller_mismatch';
    END IF;


    IF NEW.instance_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM instances
           WHERE id = NEW.instance_id
             AND controller_id = NEW.controller_id
             AND agent_id = NEW.agent_id
             AND node_id = NEW.node_id
       )
    THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT =
                'alert_instance_ownership_mismatch';
    END IF;

END$$


DELIMITER ;


-- =============================================================
-- INDEXES — ALERTS
-- =============================================================

CREATE INDEX idx_alerts_state
    ON alerts(state);

CREATE INDEX idx_alerts_level
    ON alerts(level);

CREATE INDEX idx_alerts_rule
    ON alerts(rule_id);

CREATE INDEX idx_alerts_controller
    ON alerts(controller_id);

CREATE INDEX idx_alerts_agent
    ON alerts(agent_id);

CREATE INDEX idx_alerts_node
    ON alerts(node_id);

CREATE INDEX idx_alerts_instance
    ON alerts(instance_id);

CREATE INDEX idx_alerts_scope_state
    ON alerts(
        scope,
        state
    );


-- =============================================================
-- INDEXES — ALERT EVENTS
-- =============================================================

CREATE INDEX idx_alert_events_alert
    ON alert_events(alert_id);

CREATE INDEX idx_alert_events_created
    ON alert_events(created_at);

CREATE INDEX idx_alert_events_action
    ON alert_events(action);

-- source: 011_agent_port_ranges.sql

-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 011
-- Agent managed network port ranges
-- =============================================================

CREATE TABLE agent_port_ranges (
    id BIGINT UNSIGNED NOT NULL
        AUTO_INCREMENT,

    agent_id VARCHAR(191) NOT NULL,

    protocol VARCHAR(8) NOT NULL,

    start_port INTEGER NOT NULL,

    end_port INTEGER NOT NULL,

    status VARCHAR(16) NOT NULL
        DEFAULT 'active',

    label VARCHAR(191),

    created_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),

    CONSTRAINT chk_agent_port_ranges_protocol
        CHECK (
            protocol IN (
                'tcp',
                'udp'
            )
        ),

    CONSTRAINT chk_agent_port_ranges_start
        CHECK (
            start_port BETWEEN 1 AND 65535
        ),

    CONSTRAINT chk_agent_port_ranges_end
        CHECK (
            end_port BETWEEN 1 AND 65535
        ),

    CONSTRAINT chk_agent_port_ranges_order
        CHECK (
            start_port <= end_port
        ),

    CONSTRAINT chk_agent_port_ranges_status
        CHECK (
            status IN (
                'active',
                'disabled'
            )
        ),

    CONSTRAINT fk_agent_port_ranges_agent
        FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,

    CONSTRAINT uq_agent_port_ranges
        UNIQUE (
            agent_id,
            protocol,
            start_port,
            end_port
        )
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_agent_port_ranges_agent
    ON agent_port_ranges(agent_id);

CREATE INDEX idx_agent_port_ranges_lookup
    ON agent_port_ranges(
        agent_id,
        protocol,
        status,
        start_port,
        end_port
    );

INSERT INTO agent_port_ranges(
    agent_id,
    protocol,
    start_port,
    end_port,
    status,
    label
)
SELECT
    id,
    'udp',
    24000,
    24999,
    'active',
    'default'
FROM agents;

INSERT INTO agent_port_ranges(
    agent_id,
    protocol,
    start_port,
    end_port,
    status,
    label
)
SELECT
    id,
    'tcp',
    24000,
    24999,
    'active',
    'default'
FROM agents;

DELIMITER $$

CREATE TRIGGER agents_default_port_ranges_insert
AFTER INSERT ON agents
FOR EACH ROW
BEGIN
    INSERT INTO agent_port_ranges(
        agent_id,
        protocol,
        start_port,
        end_port,
        status,
        label
    )
    VALUES
        (
            NEW.id,
            'udp',
            24000,
            24999,
            'active',
            'default'
        ),
        (
            NEW.id,
            'tcp',
            24000,
            24999,
            'active',
            'default'
        );
END$$

DELIMITER ;

-- source: 012_location_topology.sql
-- =============================================================
-- Capivara DSM MySQL / MariaDB Migration 012
-- =============================================================

CREATE TABLE regions (
    id VARCHAR(191) NOT NULL,
    name VARCHAR(191) NOT NULL,
    country_code VARCHAR(8),
    continent_code VARCHAR(8),
    latitude DOUBLE,
    longitude DOUBLE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT chk_regions_status
        CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE datacenters (
    id VARCHAR(191) NOT NULL,
    region_id VARCHAR(191) NOT NULL,
    name VARCHAR(191) NOT NULL,
    provider VARCHAR(191),
    city VARCHAR(191),
    country_code VARCHAR(8),
    latitude DOUBLE,
    longitude DOUBLE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_datacenters_region
        FOREIGN KEY (region_id)
        REFERENCES regions(id)
        ON DELETE RESTRICT,
    CONSTRAINT chk_datacenters_status
        CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE agent_locations (
    agent_id VARCHAR(191) NOT NULL,
    datacenter_id VARCHAR(191) NOT NULL,
    latitude DOUBLE,
    longitude DOUBLE,
    public_host VARCHAR(255),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (agent_id),
    CONSTRAINT fk_agent_locations_agent
        FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_agent_locations_datacenter
        FOREIGN KEY (datacenter_id)
        REFERENCES datacenters(id)
        ON DELETE RESTRICT,
    CONSTRAINT chk_agent_locations_status
        CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE controller_placement_policies (
    controller_id VARCHAR(191) NOT NULL,
    mode VARCHAR(32) NOT NULL DEFAULT 'latency_assisted',
    customer_region_selection BOOLEAN NOT NULL DEFAULT TRUE,
    cross_region_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    max_latency_ms INTEGER,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (controller_id),
    CONSTRAINT chk_placement_policy_mode
        CHECK (mode IN (
            'controller',
            'customer_region',
            'latency_assisted'
        ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_datacenters_region
    ON datacenters(region_id, status);

CREATE INDEX idx_agent_locations_datacenter
    ON agent_locations(datacenter_id, status);

-- source: 013_controller_placement_policy_fk.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 013
-- Enforce Controller ownership for placement policies
-- =============================================================

ALTER TABLE controller_placement_policies
    ADD CONSTRAINT fk_controller_placement_policies_controller
    FOREIGN KEY (controller_id)
    REFERENCES controllers(id)
    ON DELETE CASCADE;

-- source: 014_customer_account_identity.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 014
-- Customer self-service account identity and SFTP username
-- =============================================================

ALTER TABLE customers
    ADD COLUMN account_email VARCHAR(320),
    ADD COLUMN sftp_username VARCHAR(191),
    ADD COLUMN registration_status VARCHAR(32) NOT NULL DEFAULT 'managed',
    ADD COLUMN email_verified_at DATETIME(6),
    ADD CONSTRAINT chk_customers_registration_status
        CHECK (registration_status IN (
            'managed',
            'pending',
            'active',
            'disabled'
        ));

CREATE UNIQUE INDEX idx_customers_account_email
    ON customers(account_email);

CREATE UNIQUE INDEX idx_customers_sftp_username
    ON customers(sftp_username);

-- source: 015_customer_account_access.sql
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

-- source: 016_customer_account_integrity.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- MySQL / MariaDB Migration 016 - customer_account integrity parity
-- MySQL has no PostgreSQL/SQLite-style partial unique index, therefore a
-- generated nullable owner key provides the same one-owner-per-Customer rule.
-- =============================================================
ALTER TABLE customer_account_members
    ADD COLUMN owner_customer_id VARCHAR(191)
        GENERATED ALWAYS AS (
            CASE
                WHEN account_role = 'owner' THEN customer_id
                ELSE NULL
            END
        ) STORED,
    ADD UNIQUE KEY uq_customer_account_owner (owner_customer_id);

-- source: 017_customer_user_identity_and_invitations.sql
-- Capivara DSM MySQL migration 017 - per-login e-mail identity and invitations
CREATE TABLE customer_user_identities (
    username VARCHAR(191) NOT NULL,
    email VARCHAR(320) NOT NULL,
    email_verified_at DATETIME(6),
    PRIMARY KEY (username),
    UNIQUE KEY uq_customer_user_identity_email (email),
    CONSTRAINT fk_customer_user_identity_user FOREIGN KEY (username)
        REFERENCES dashboard_users(username) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO customer_user_identities(username,email,email_verified_at)
SELECT m.username,c.account_email,c.email_verified_at
FROM customer_account_members m
JOIN customers c ON c.id=m.customer_id
WHERE m.account_role='owner'
  AND c.account_email IS NOT NULL;

CREATE TABLE customer_invitations (
    id VARCHAR(191) NOT NULL,
    customer_id VARCHAR(191) NOT NULL,
    email VARCHAR(320) NOT NULL,
    account_role VARCHAR(32) NOT NULL,
    token_hash CHAR(64) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    accepted_at DATETIME(6),
    revoked_at DATETIME(6),
    invited_by VARCHAR(191) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_customer_invitations_token (token_hash),
    CONSTRAINT chk_customer_invitation_role CHECK (account_role IN ('manager','member')),
    CONSTRAINT fk_customer_invitation_customer FOREIGN KEY (customer_id)
        REFERENCES customers(id) ON DELETE CASCADE,
    CONSTRAINT fk_customer_invitation_actor FOREIGN KEY (invited_by)
        REFERENCES dashboard_users(username) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_customer_invitations_customer ON customer_invitations(customer_id, created_at);
CREATE INDEX idx_customer_invitations_email ON customer_invitations(email, expires_at);

CREATE TABLE customer_invitation_access (
    invitation_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NOT NULL,
    permission_profile VARCHAR(32) NOT NULL,
    PRIMARY KEY (invitation_id, instance_id),
    CONSTRAINT chk_customer_invitation_access_profile CHECK (permission_profile IN ('viewer','operator','manager')),
    CONSTRAINT fk_customer_invitation_access_invite FOREIGN KEY (invitation_id)
        REFERENCES customer_invitations(id) ON DELETE CASCADE,
    CONSTRAINT fk_customer_invitation_access_instance FOREIGN KEY (instance_id)
        REFERENCES instances(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- source: 018_customer_email_verification.sql
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

-- source: 019_customer_account_legacy_backfill.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 019
-- Legacy customer account membership and identity backfill
-- MySQL / MariaDB
-- =============================================================

INSERT INTO customer_account_members (
    customer_id,
    username,
    account_role
)
SELECT
    c.id,
    u.username,
    'owner'
FROM dashboard_users u
JOIN customers c
    ON c.id = u.scope_id
WHERE u.role = 'customer'
  AND NOT EXISTS (
      SELECT 1
      FROM customer_account_members m
      WHERE m.customer_id = c.id
        AND m.username = u.username
  )
  AND NOT EXISTS (
      SELECT 1
      FROM customer_account_members owner_account
      WHERE owner_account.customer_id = c.id
        AND owner_account.account_role = 'owner'
  );


INSERT INTO customer_user_identities (
    username,
    email,
    email_verified_at
)
SELECT
    m.username,
    c.account_email,
    c.email_verified_at
FROM customer_account_members m
JOIN customers c
    ON c.id = m.customer_id
WHERE m.account_role = 'owner'
  AND c.account_email IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM customer_user_identities i
      WHERE i.username = m.username
  );

CREATE TABLE agent_runtime_inventory (
 agent_id VARCHAR(191) PRIMARY KEY, hostname TEXT, os_name TEXT, architecture TEXT,
 capivara_version TEXT, address TEXT, fingerprint VARCHAR(191),
 capabilities_json JSON NOT NULL, cpu_json JSON NOT NULL, ram_total_bytes BIGINT,
 storage_json JSON NOT NULL, health_status VARCHAR(16) NOT NULL DEFAULT 'offline',
 last_seen DATETIME(6), heartbeat_interval_seconds INT NOT NULL DEFAULT 30,
 degraded_after_seconds INT NOT NULL DEFAULT 60, offline_after_seconds INT NOT NULL DEFAULT 120,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 CONSTRAINT fk_runtime_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE,
 CONSTRAINT chk_runtime_health CHECK (health_status IN ('online','degraded','offline')),
 CONSTRAINT chk_runtime_intervals CHECK (heartbeat_interval_seconds > 0 AND degraded_after_seconds >= heartbeat_interval_seconds AND offline_after_seconds > degraded_after_seconds),
 INDEX idx_agent_runtime_health(health_status,last_seen), INDEX idx_agent_runtime_fingerprint(fingerprint)
) ENGINE=InnoDB;
CREATE TABLE agent_pairing_tokens (
 id VARCHAR(191) PRIMARY KEY, controller_id VARCHAR(191) NOT NULL,
 token_hash VARCHAR(191) NOT NULL UNIQUE, expires_at DATETIME(6) NOT NULL,
 consumed_at DATETIME(6), created_by TEXT, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 CONSTRAINT fk_pairing_controller FOREIGN KEY(controller_id) REFERENCES controllers(id) ON DELETE CASCADE,
 INDEX idx_agent_pairing_tokens_controller(controller_id,expires_at,consumed_at)
) ENGINE=InnoDB;
CREATE TABLE agent_credentials (
 id VARCHAR(191) PRIMARY KEY, agent_id VARCHAR(191) NOT NULL, controller_id VARCHAR(191) NOT NULL,
 credential_type VARCHAR(64) NOT NULL DEFAULT 'opaque-v1', secret_hash TEXT,
 fingerprint VARCHAR(191) NOT NULL, public_key TEXT, status VARCHAR(16) NOT NULL DEFAULT 'active',
 issued_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), last_used_at DATETIME(6), revoked_at DATETIME(6),
 CONSTRAINT fk_credentials_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE,
 CONSTRAINT fk_credentials_controller FOREIGN KEY(controller_id) REFERENCES controllers(id) ON DELETE CASCADE,
 CONSTRAINT uq_credentials_agent UNIQUE(agent_id,id), CONSTRAINT chk_credentials_status CHECK(status IN ('active','revoked')),
 INDEX idx_agent_credentials_agent(agent_id,status), INDEX idx_agent_credentials_fingerprint(fingerprint,status)
) ENGINE=InnoDB;
-- source: 022_agent_installation_tracking.sql
ALTER TABLE agent_pairing_tokens ADD COLUMN platform VARCHAR(32) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN install_method VARCHAR(32) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN region_id VARCHAR(191) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN datacenter_id VARCHAR(191) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN agent_id VARCHAR(191) NULL;

CREATE INDEX idx_agent_pairing_tokens_agent_id
    ON agent_pairing_tokens(agent_id);
CREATE INDEX idx_agent_pairing_tokens_datacenter_id
    ON agent_pairing_tokens(datacenter_id);

-- source: 023_agent_network_inventory.sql
ALTER TABLE agent_runtime_inventory ADD COLUMN network_json LONGTEXT NULL;

-- source: 024_agent_remote_updates.sql
-- Capivara DSM - Migration 024 - MySQL/MariaDB
CREATE TABLE agent_update_state (
    agent_id VARCHAR(191) PRIMARY KEY,
    installed_version VARCHAR(64),
    available_version VARCHAR(64),
    update_channel VARCHAR(32) NOT NULL DEFAULT 'stable',
    desired_version VARCHAR(64),
    update_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    rollout_id VARCHAR(191),
    batch_number INTEGER,
    batch_position INTEGER,
    requested_at VARCHAR(64),
    last_update VARCHAR(64),
    last_error TEXT,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_agent_update_state_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_update_channel CHECK (update_channel IN ('stable','beta','local/manual')),
    CONSTRAINT chk_agent_update_status CHECK (update_status IN ('idle','planned','updating','verifying','completed','failed'))
);
CREATE INDEX idx_agent_update_rollout ON agent_update_state(rollout_id,batch_number,batch_position);
CREATE INDEX idx_agent_update_status ON agent_update_state(update_status,update_channel);

-- source: 025_agent_game_data_jobs.sql
-- Capivara DSM - Migration 025 - MySQL/MariaDB
-- Agent-owned game-data command queue.

CREATE TABLE agent_game_data_jobs (
    job_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    action VARCHAR(16) NOT NULL,
    environment_id VARCHAR(191) NOT NULL,
    selector VARCHAR(191) NOT NULL,
    selection_json LONGTEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    requested_by VARCHAR(191),
    result_json LONGTEXT,
    last_error TEXT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at DATETIME(6) NULL,
    started_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_game_data_jobs_agent
        FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_game_data_jobs_action
        CHECK (action IN ('install','update','verify')),
    CONSTRAINT chk_agent_game_data_jobs_status
        CHECK (status IN ('queued','delivered','running','completed','failed')),
    CONSTRAINT chk_agent_game_data_jobs_progress
        CHECK (progress >= 0 AND progress <= 100)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_agent_game_data_jobs_agent_status
    ON agent_game_data_jobs(agent_id,status,created_at);

CREATE INDEX idx_agent_game_data_jobs_environment
    ON agent_game_data_jobs(agent_id,environment_id,status);

-- source: 026_agent_installation_preconfiguration.sql
-- Capivara DSM - Migration 026 - MySQL/MariaDB
-- Preconfiguration attached to an Agent installation before enrollment.
-- 025 is intentionally reserved by the open Agent game-data orchestration work.

CREATE TABLE agent_installation_preconfiguration (
    installation_id VARCHAR(191) PRIMARY KEY,
    requested_name VARCHAR(128),
    port_protocol VARCHAR(8),
    port_start INTEGER,
    port_end INTEGER,
    applied_at TIMESTAMP(6) NULL,
    apply_error TEXT,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_install_preconfig_installation
        FOREIGN KEY (installation_id)
        REFERENCES agent_pairing_tokens(id)
        ON DELETE CASCADE,
    CONSTRAINT chk_agent_install_preconfig_protocol
        CHECK (port_protocol IN ('tcp','udp','both') OR port_protocol IS NULL),
    CONSTRAINT chk_agent_install_preconfig_range
        CHECK (
            (port_start IS NULL AND port_end IS NULL AND port_protocol IS NULL)
            OR
            (port_start BETWEEN 1 AND 65535
             AND port_end BETWEEN port_start AND 65535
             AND port_protocol IS NOT NULL)
        )
);

CREATE INDEX idx_agent_install_preconfig_applied
    ON agent_installation_preconfiguration(applied_at, apply_error(191));

-- source: 027_agent_instance_runtime_commands.sql
-- Capivara DSM - Migration 027 - MySQL/MariaDB
CREATE TABLE agent_instance_commands (
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
    CONSTRAINT fk_agent_instance_commands_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_commands_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_commands_action CHECK (action IN ('status','doctor')),
    CONSTRAINT chk_agent_instance_commands_status CHECK (status IN ('queued','delivered','completed','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX idx_agent_instance_commands_agent_status ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance ON agent_instance_commands(instance_id,created_at);

-- source: 028_agent_instance_lifecycle_actions.sql
-- Capivara DSM - Migration 028 - MySQL/MariaDB
-- Rebuild the B6 command table so lifecycle actions have an explicit allowlist.

CREATE TABLE agent_instance_commands_v2 (
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
    CONSTRAINT fk_agent_instance_commands_v2_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_commands_v2_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_commands_v2_action CHECK (action IN ('status','doctor','start','stop','restart')),
    CONSTRAINT chk_agent_instance_commands_v2_status CHECK (status IN ('queued','delivered','completed','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO agent_instance_commands_v2
(command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at)
SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at
FROM agent_instance_commands;

DROP TABLE agent_instance_commands;
RENAME TABLE agent_instance_commands_v2 TO agent_instance_commands;

CREATE INDEX idx_agent_instance_commands_agent_status ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance ON agent_instance_commands(instance_id,created_at);

-- source: 029_agent_instance_provisioning.sql
-- Capivara DSM - Migration 029 - MySQL
-- B10 persistent Controller -> Agent instance provisioning pipeline.

CREATE TABLE agent_instance_provisioning (
    provisioning_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NOT NULL,
    environment_id VARCHAR(191) NOT NULL,
    selector VARCHAR(191) NOT NULL,
    request_json LONGTEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    current_step VARCHAR(128) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    requested_by VARCHAR(191) NULL,
    result_json LONGTEXT NULL,
    last_error TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivered_at DATETIME(6) NULL,
    started_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_agent_instance_provisioning_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_instance_provisioning_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT chk_agent_instance_provisioning_status CHECK (status IN ('queued','delivered','running','completed','failed')),
    CONSTRAINT chk_agent_instance_provisioning_progress CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX idx_agent_instance_provisioning_agent_status
    ON agent_instance_provisioning(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_provisioning_instance
    ON agent_instance_provisioning(instance_id,created_at);

-- source: 030_agent_instance_reconciliation.sql
-- Capivara DSM - Migration 030 - MySQL
CREATE TABLE agent_instance_reconciliation (
    instance_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    desired_state VARCHAR(32) NULL,
    observed_state VARCHAR(32) NULL,
    reconcile_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    retry_count INT NOT NULL DEFAULT 0,
    last_attempt_at VARCHAR(64) NULL,
    last_success_at VARCHAR(64) NULL,
    next_retry_at VARCHAR(64) NULL,
    last_error TEXT NULL,
    drift VARCHAR(128) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_reconcile_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT fk_reconcile_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX idx_agent_instance_reconciliation_agent_status
    ON agent_instance_reconciliation(agent_id,reconcile_status,updated_at);

-- source: 031_agent_instance_runtime_health.sql
-- Capivara DSM - Migration 031 - MySQL
CREATE TABLE agent_instance_runtime_health (
    instance_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    desired_state VARCHAR(32) NULL,
    observed_state VARCHAR(32) NULL,
    reconcile_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    health VARCHAR(32) NOT NULL DEFAULT 'unknown',
    operation_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    operation_name VARCHAR(64) NULL,
    last_error TEXT NULL,
    last_transition_at VARCHAR(64) NULL,
    reported_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_runtime_health_instance FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    CONSTRAINT fk_runtime_health_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX idx_agent_instance_runtime_health_agent
    ON agent_instance_runtime_health(agent_id,health,updated_at);

-- source: 032_universal_events.sql
-- Capivara DSM - Migration 032 - MySQL/MariaDB
-- Subject identifiers intentionally have no foreign keys so immutable event
-- history survives deletion or re-creation of infrastructure entities.
CREATE TABLE universal_events (
    event_id VARCHAR(191) PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    event_type VARCHAR(128) NOT NULL,
    occurred_at VARCHAR(64) NOT NULL,
    received_at VARCHAR(64) NOT NULL,
    source VARCHAR(128) NOT NULL,
    source_id VARCHAR(191) NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'info',
    agent_id VARCHAR(191) NULL,
    instance_id VARCHAR(191) NULL,
    correlation_id VARCHAR(191) NULL,
    causation_id VARCHAR(191) NULL,
    actor_type VARCHAR(64) NULL,
    actor_id VARCHAR(191) NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX idx_universal_events_type_time ON universal_events(event_type, occurred_at);
CREATE INDEX idx_universal_events_agent_time ON universal_events(agent_id, occurred_at);
CREATE INDEX idx_universal_events_instance_time ON universal_events(instance_id, occurred_at);
CREATE INDEX idx_universal_events_severity_time ON universal_events(severity, occurred_at);
CREATE INDEX idx_universal_events_correlation ON universal_events(correlation_id, occurred_at);

-- source: 033_universal_configuration.sql
-- Capivara DSM - Migration 033 - MySQL/MariaDB
CREATE TABLE configurations (
    configuration_id VARCHAR(191) PRIMARY KEY,
    scope_type VARCHAR(32) NOT NULL,
    scope_key VARCHAR(191) NOT NULL,
    namespace VARCHAR(128) NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL,
    value_json LONGTEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    updated_by VARCHAR(191) NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_configurations_scope UNIQUE(scope_type, scope_key, namespace)
);
CREATE TABLE configuration_revisions (
    configuration_id VARCHAR(191) NOT NULL,
    revision INTEGER NOT NULL,
    value_json LONGTEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    updated_by VARCHAR(191) NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(configuration_id, revision)
);
CREATE TABLE agent_configuration_state (
    agent_id VARCHAR(191) NOT NULL,
    target_type VARCHAR(32) NOT NULL,
    target_id VARCHAR(191) NOT NULL,
    namespace VARCHAR(128) NOT NULL,
    desired_revision VARCHAR(64) NOT NULL,
    applied_revision VARCHAR(64) NULL,
    desired_checksum VARCHAR(64) NOT NULL,
    applied_checksum VARCHAR(64) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    last_error TEXT NULL,
    reported_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(agent_id, target_type, target_id, namespace),
    CONSTRAINT fk_agent_configuration_state_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX idx_configurations_scope_namespace ON configurations(scope_type, scope_key, namespace);
CREATE INDEX idx_configuration_revisions_created ON configuration_revisions(configuration_id, revision);
CREATE INDEX idx_agent_configuration_state_pending ON agent_configuration_state(agent_id, status, target_type, target_id, namespace);

-- source: 034_universal_observability.sql
-- Capivara DSM - Migration 034 - MySQL/MariaDB
CREATE TABLE observability_samples (
    sample_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL,
    instance_id VARCHAR(191) NULL,
    scope_type VARCHAR(32) NOT NULL,
    metric_name VARCHAR(191) NOT NULL,
    metric_type VARCHAR(32) NOT NULL,
    value_double DOUBLE NOT NULL,
    unit VARCHAR(32) NOT NULL,
    dimensions_json LONGTEXT NOT NULL,
    collected_at VARCHAR(64) NOT NULL,
    ingested_at VARCHAR(64) NOT NULL
);
CREATE TABLE observability_latest (
    agent_id VARCHAR(191) NOT NULL,
    subject_key VARCHAR(191) NOT NULL,
    metric_name VARCHAR(191) NOT NULL,
    dimensions_key VARCHAR(64) NOT NULL,
    sample_id VARCHAR(191) NOT NULL,
    value_double DOUBLE NOT NULL,
    unit VARCHAR(32) NOT NULL,
    metric_type VARCHAR(32) NOT NULL,
    dimensions_json LONGTEXT NOT NULL,
    collected_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(agent_id, subject_key, metric_name, dimensions_key)
);
CREATE INDEX idx_observability_samples_agent_time ON observability_samples(agent_id, collected_at);
CREATE INDEX idx_observability_samples_instance_time ON observability_samples(instance_id, collected_at);
CREATE INDEX idx_observability_samples_metric_time ON observability_samples(metric_name, collected_at);
CREATE INDEX idx_observability_latest_agent ON observability_latest(agent_id, subject_key, metric_name);

-- source: 035_universal_content.sql
-- Capivara DSM - Migration 035 - MySQL/MariaDB
CREATE TABLE content_assignments (
 assignment_id VARCHAR(191) PRIMARY KEY, instance_id VARCHAR(191) NOT NULL, agent_id VARCHAR(191) NOT NULL,
 content_id VARCHAR(191) NOT NULL, game_id VARCHAR(191) NOT NULL, content_type VARCHAR(32) NOT NULL,
 desired_state VARCHAR(16) NOT NULL, version VARCHAR(191) NOT NULL, provider VARCHAR(64) NOT NULL, target VARCHAR(500) NOT NULL,
 artifact_json LONGTEXT NOT NULL, dependencies_json LONGTEXT NOT NULL, conflicts_json LONGTEXT NOT NULL,
 revision BIGINT NOT NULL, checksum CHAR(64) NOT NULL, requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
 UNIQUE KEY uq_content_instance_id(instance_id,content_id), KEY idx_content_assignments_agent(agent_id,instance_id,desired_state)
);
CREATE TABLE content_assignment_revisions (
 assignment_id VARCHAR(191) NOT NULL, revision BIGINT NOT NULL, desired_state VARCHAR(16) NOT NULL,
 version VARCHAR(191) NOT NULL, provider VARCHAR(64) NOT NULL, target VARCHAR(500) NOT NULL, artifact_json LONGTEXT NOT NULL,
 dependencies_json LONGTEXT NOT NULL, conflicts_json LONGTEXT NOT NULL, checksum CHAR(64) NOT NULL,
 requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, PRIMARY KEY(assignment_id,revision)
);
CREATE TABLE agent_content_state (
 agent_id VARCHAR(191) NOT NULL, instance_id VARCHAR(191) NOT NULL, content_id VARCHAR(191) NOT NULL,
 desired_revision BIGINT NOT NULL, applied_revision BIGINT, desired_checksum CHAR(64) NOT NULL, applied_checksum CHAR(64),
 status VARCHAR(32) NOT NULL, installed_version VARCHAR(191), last_error TEXT, reported_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
 PRIMARY KEY(agent_id,instance_id,content_id), KEY idx_agent_content_state_agent(agent_id,status)
);

-- source: 036_universal_smart_backup.sql
CREATE TABLE IF NOT EXISTS backup_policies (
 policy_id VARCHAR(191) PRIMARY KEY, instance_id VARCHAR(191) NOT NULL UNIQUE, agent_id VARCHAR(191) NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
 mode VARCHAR(32) NOT NULL, consistency VARCHAR(32) NOT NULL, compression VARCHAR(32) NOT NULL, interval_seconds INT NOT NULL,
 retention_count INT NOT NULL, include_json LONGTEXT NOT NULL, exclude_json LONGTEXT NOT NULL, revision INT NOT NULL, checksum VARCHAR(64) NOT NULL,
 requested_by VARCHAR(191), created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_backup_policy_instance FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE,
 CONSTRAINT fk_backup_policy_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS backup_policy_revisions (
 policy_id VARCHAR(191) NOT NULL, revision INT NOT NULL, enabled BOOLEAN NOT NULL, mode VARCHAR(32) NOT NULL, consistency VARCHAR(32) NOT NULL,
 compression VARCHAR(32) NOT NULL, interval_seconds INT NOT NULL, retention_count INT NOT NULL, include_json LONGTEXT NOT NULL,
 exclude_json LONGTEXT NOT NULL, checksum VARCHAR(64) NOT NULL, requested_by VARCHAR(191), created_at VARCHAR(64) NOT NULL,
 PRIMARY KEY(policy_id,revision), CONSTRAINT fk_backup_revision_policy FOREIGN KEY(policy_id) REFERENCES backup_policies(policy_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS backup_jobs (
 command_id VARCHAR(191) PRIMARY KEY, backup_id VARCHAR(191) UNIQUE, instance_id VARCHAR(191) NOT NULL, agent_id VARCHAR(191) NOT NULL,
 action VARCHAR(32) NOT NULL, policy_revision INT, status VARCHAR(32) NOT NULL DEFAULT 'pending', reason VARCHAR(64), requested_by VARCHAR(191),
 size_bytes BIGINT, sha256 VARCHAR(64), artifact_path TEXT, started_at VARCHAR(64), completed_at VARCHAR(64), last_error TEXT,
 created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_backup_job_instance FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE,
 CONSTRAINT fk_backup_job_agent FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE,
 INDEX idx_backup_jobs_agent_status(agent_id,status,created_at), INDEX idx_backup_jobs_instance_completed(instance_id,completed_at)
);

-- source: 037_automation_broadcast.sql
CREATE TABLE IF NOT EXISTS automation_rules (
 rule_id VARCHAR(191) PRIMARY KEY, name VARCHAR(191) NOT NULL, enabled TINYINT NOT NULL DEFAULT 1, trigger_json LONGTEXT NOT NULL,
 conditions_json LONGTEXT NOT NULL, actions_json LONGTEXT NOT NULL, cooldown_seconds INT NOT NULL DEFAULT 0,
 revision INT NOT NULL, checksum VARCHAR(64) NOT NULL, requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_rule_revisions (
 rule_id VARCHAR(191) NOT NULL, revision INT NOT NULL, name VARCHAR(191) NOT NULL, enabled TINYINT NOT NULL, trigger_json LONGTEXT NOT NULL,
 conditions_json LONGTEXT NOT NULL, actions_json LONGTEXT NOT NULL, cooldown_seconds INT NOT NULL, checksum VARCHAR(64) NOT NULL,
 requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, PRIMARY KEY(rule_id,revision),
 FOREIGN KEY(rule_id) REFERENCES automation_rules(rule_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS automation_runs (
 run_id VARCHAR(191) PRIMARY KEY, rule_id VARCHAR(191), trigger_type VARCHAR(32) NOT NULL, trigger_ref VARCHAR(191), status VARCHAR(32) NOT NULL DEFAULT 'pending',
 context_json LONGTEXT NOT NULL, result_json LONGTEXT NOT NULL, requested_by VARCHAR(191), started_at VARCHAR(40), completed_at VARCHAR(40), created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
 INDEX idx_automation_runs_rule_created(rule_id,created_at), UNIQUE KEY uq_automation_run_trigger(rule_id,trigger_type,trigger_ref)
);
CREATE TABLE IF NOT EXISTS automation_runtime_state (
 state_key VARCHAR(191) PRIMARY KEY, state_value LONGTEXT NOT NULL, updated_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS broadcasts (
 broadcast_id VARCHAR(191) PRIMARY KEY, scope VARCHAR(32) NOT NULL, target VARCHAR(191), message TEXT NOT NULL, priority VARCHAR(16) NOT NULL,
 ttl_seconds INT NOT NULL, require_ack TINYINT NOT NULL DEFAULT 1, status VARCHAR(32) NOT NULL DEFAULT 'pending', requested_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, expires_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS broadcast_deliveries (
 delivery_id VARCHAR(191) PRIMARY KEY, broadcast_id VARCHAR(191) NOT NULL, agent_id VARCHAR(191) NOT NULL, instance_id VARCHAR(191),
 status VARCHAR(32) NOT NULL DEFAULT 'pending', attempts INT NOT NULL DEFAULT 0, delivered_at VARCHAR(40), acknowledged_at VARCHAR(40), last_error TEXT, updated_at VARCHAR(40) NOT NULL,
 UNIQUE KEY uq_broadcast_delivery(broadcast_id,agent_id,instance_id), INDEX idx_broadcast_delivery_agent_status(agent_id,status,updated_at),
 FOREIGN KEY(broadcast_id) REFERENCES broadcasts(broadcast_id) ON DELETE CASCADE, FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- source: 038_realtime_api_platform.sql
-- Capivara DSM - Migration 038 - MySQL/MariaDB
CREATE TABLE IF NOT EXISTS api_tokens (
 token_id VARCHAR(191) PRIMARY KEY, name VARCHAR(191) NOT NULL, token_prefix VARCHAR(191) NOT NULL UNIQUE, secret_hash VARCHAR(64) NOT NULL,
 scopes_json LONGTEXT NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active', expires_at VARCHAR(40), last_used_at VARCHAR(40),
 created_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, revoked_at VARCHAR(40), INDEX idx_api_tokens_status(status,expires_at)
);
CREATE TABLE IF NOT EXISTS api_request_log (
 request_id VARCHAR(191) PRIMARY KEY, token_id VARCHAR(191), method VARCHAR(16) NOT NULL, path VARCHAR(512) NOT NULL,
 status_code INT NOT NULL, latency_ms DOUBLE, remote_address VARCHAR(191), created_at VARCHAR(40) NOT NULL,
 INDEX idx_api_request_log_token_time(token_id,created_at), INDEX idx_api_request_log_time(created_at),
 FOREIGN KEY(token_id) REFERENCES api_tokens(token_id) ON DELETE SET NULL
);

-- source: 039_multi_datacenter_federation.sql
-- Capivara DSM - Migration 039 - MySQL/MariaDB
-- E1 Multi-Datacenter Federation.
CREATE TABLE IF NOT EXISTS federation_members (
 controller_id VARCHAR(191) PRIMARY KEY,
 role VARCHAR(32) NOT NULL, region_id VARCHAR(191) NULL, datacenter_id VARCHAR(191) NULL,
 public_endpoint TEXT NULL, credential_hash TEXT NULL, status VARCHAR(32) NOT NULL DEFAULT 'pending',
 last_seen_at VARCHAR(64) NULL, created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_fed_member_controller FOREIGN KEY(controller_id) REFERENCES controllers(id) ON DELETE CASCADE,
 CONSTRAINT fk_fed_member_region FOREIGN KEY(region_id) REFERENCES regions(id) ON DELETE RESTRICT,
 CONSTRAINT fk_fed_member_dc FOREIGN KEY(datacenter_id) REFERENCES datacenters(id) ON DELETE RESTRICT
);
CREATE INDEX idx_federation_members_location ON federation_members(region_id,datacenter_id,status);
CREATE TABLE IF NOT EXISTS federation_inventory_snapshots (
 snapshot_id VARCHAR(191) PRIMARY KEY, controller_id VARCHAR(191) NOT NULL,
 generated_at VARCHAR(64) NOT NULL, payload_json LONGTEXT NOT NULL, received_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_fed_snapshot_member FOREIGN KEY(controller_id) REFERENCES federation_members(controller_id) ON DELETE CASCADE
);
CREATE INDEX idx_federation_inventory_member_time ON federation_inventory_snapshots(controller_id,generated_at);
CREATE TABLE IF NOT EXISTS federation_policies (
 policy_id VARCHAR(191) PRIMARY KEY, scope_type VARCHAR(32) NOT NULL, scope_id VARCHAR(191) NULL,
 mode VARCHAR(32) NOT NULL DEFAULT 'local_first', cross_region_fallback TINYINT NOT NULL DEFAULT 0,
 max_latency_ms INT NULL, payload_json LONGTEXT NOT NULL, revision INT NOT NULL DEFAULT 1,
 created_at VARCHAR(64) NOT NULL, updated_at VARCHAR(64) NOT NULL
);
CREATE INDEX idx_federation_policies_scope ON federation_policies(scope_type,scope_id);
CREATE TABLE IF NOT EXISTS federation_event_cursors (
 controller_id VARCHAR(191) PRIMARY KEY, last_event_id VARCHAR(191) NULL, updated_at VARCHAR(64) NOT NULL,
 CONSTRAINT fk_fed_cursor_member FOREIGN KEY(controller_id) REFERENCES federation_members(controller_id) ON DELETE CASCADE
);

-- source: 040_high_availability_disaster_recovery.sql
CREATE TABLE IF NOT EXISTS ha_clusters (
    cluster_id VARCHAR(191) PRIMARY KEY,
    name VARCHAR(191) NOT NULL,
    mode VARCHAR(32) NOT NULL DEFAULT 'manual',
    rpo_seconds INTEGER NOT NULL DEFAULT 300,
    rto_seconds INTEGER NOT NULL DEFAULT 900,
    quorum_size INTEGER NOT NULL DEFAULT 2,
    auto_failback BOOLEAN NOT NULL DEFAULT FALSE,
    fencing_epoch BIGINT NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);
CREATE TABLE IF NOT EXISTS ha_cluster_members (
    cluster_id VARCHAR(191) NOT NULL,
    controller_id VARCHAR(191) NOT NULL,
    role VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'unknown',
    priority INTEGER NOT NULL DEFAULT 100,
    last_seen_at VARCHAR(64),
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY(cluster_id, controller_id)
);
CREATE INDEX idx_ha_members_state ON ha_cluster_members(cluster_id, role, state, priority);
CREATE TABLE IF NOT EXISTS dr_recovery_points (
    recovery_point_id VARCHAR(191) PRIMARY KEY,
    cluster_id VARCHAR(191) NOT NULL,
    source_controller_id VARCHAR(191) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL,
    location TEXT NOT NULL,
    checksum VARCHAR(128),
    metadata_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    validated_at VARCHAR(64)
);
CREATE INDEX idx_dr_points_cluster ON dr_recovery_points(cluster_id, created_at);
CREATE TABLE IF NOT EXISTS ha_failover_operations (
    operation_id VARCHAR(191) PRIMARY KEY,
    cluster_id VARCHAR(191) NOT NULL,
    source_controller_id VARCHAR(191),
    target_controller_id VARCHAR(191) NOT NULL,
    state VARCHAR(32) NOT NULL,
    reason TEXT,
    requested_by VARCHAR(191),
    automatic BOOLEAN NOT NULL DEFAULT FALSE,
    fencing_epoch BIGINT NOT NULL,
    message TEXT,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    completed_at VARCHAR(64)
);
CREATE INDEX idx_ha_failover_cluster ON ha_failover_operations(cluster_id, created_at);

-- source: 041_admin_destructive_deletion.sql
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

