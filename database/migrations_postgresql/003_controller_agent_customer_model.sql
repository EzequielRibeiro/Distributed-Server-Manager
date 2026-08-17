-- =============================================================
-- Capivara Distributed Server Manager
-- PostgreSQL Migration 003
-- Controller / Agent / Customer ownership model
-- =============================================================

CREATE TABLE controllers (
    id TEXT PRIMARY KEY,

    node_id TEXT NOT NULL UNIQUE,

    name TEXT NOT NULL,

    status TEXT NOT NULL
        DEFAULT 'active',

    metadata_json JSONB NOT NULL
        DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_controllers_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE RESTRICT
);


CREATE TABLE agents (
    id TEXT PRIMARY KEY,

    controller_id TEXT NOT NULL,
    node_id TEXT NOT NULL UNIQUE,

    name TEXT NOT NULL,

    status TEXT NOT NULL
        DEFAULT 'pending',

    metadata_json JSONB NOT NULL
        DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_agents_controller
        FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_agents_node
        FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE RESTRICT
);


CREATE TABLE customers (
    id TEXT PRIMARY KEY,

    controller_id TEXT NOT NULL,

    name TEXT NOT NULL,

    email TEXT,
    phone TEXT,

    status TEXT NOT NULL
        DEFAULT 'active',

    metadata_json JSONB NOT NULL
        DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_customers_controller
        FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE RESTRICT
);


ALTER TABLE instances
    ADD COLUMN controller_id TEXT;

ALTER TABLE instances
    ADD COLUMN agent_id TEXT;

ALTER TABLE instances
    ADD COLUMN customer_id TEXT;


-- PostgreSQL starts from a clean database in this backend.
-- Keep the historical migration semantics explicit.
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


-- =============================================================
-- Controller node validation
-- =============================================================

CREATE OR REPLACE FUNCTION
validate_controller_node()
RETURNS trigger
LANGUAGE plpgsql
AS $$
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
        RAISE EXCEPTION
            'controller_requires_controller_node';
    END IF;

    RETURN NEW;
END;
$$;


CREATE TRIGGER controllers_require_controller_node_insert
BEFORE INSERT OR UPDATE OF node_id
ON controllers
FOR EACH ROW
EXECUTE FUNCTION validate_controller_node();


-- =============================================================
-- Agent node validation
-- =============================================================

CREATE OR REPLACE FUNCTION
validate_agent_node()
RETURNS trigger
LANGUAGE plpgsql
AS $$
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
        RAISE EXCEPTION
            'agent_requires_agent_node';
    END IF;

    RETURN NEW;
END;
$$;


CREATE TRIGGER agents_require_agent_node_insert
BEFORE INSERT OR UPDATE OF node_id
ON agents
FOR EACH ROW
EXECUTE FUNCTION validate_agent_node();


-- =============================================================
-- Instance ownership validation
-- =============================================================

CREATE OR REPLACE FUNCTION
validate_instance_ownership()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.controller_id IS NULL
       OR NEW.agent_id IS NULL
       OR NEW.customer_id IS NULL
    THEN
        RAISE EXCEPTION
            'instance_requires_controller_agent_customer';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM agents
        WHERE id = NEW.agent_id
          AND controller_id = NEW.controller_id
          AND node_id = NEW.node_id
    ) THEN
        RAISE EXCEPTION
            'instance_agent_controller_mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM customers
        WHERE id = NEW.customer_id
          AND controller_id = NEW.controller_id
    ) THEN
        RAISE EXCEPTION
            'instance_customer_controller_mismatch';
    END IF;

    RETURN NEW;
END;
$$;


CREATE TRIGGER instances_require_ownership
BEFORE INSERT OR UPDATE OF
    controller_id,
    agent_id,
    customer_id,
    node_id
ON instances
FOR EACH ROW
EXECUTE FUNCTION validate_instance_ownership();


CREATE INDEX idx_agents_controller
    ON agents(controller_id);

CREATE INDEX idx_customers_controller
    ON customers(controller_id);

CREATE INDEX idx_instances_ownership
    ON instances(
        controller_id,
        agent_id,
        customer_id
    );
