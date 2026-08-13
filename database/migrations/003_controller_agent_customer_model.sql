CREATE TABLE controllers (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE RESTRICT
);

CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    node_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (controller_id) REFERENCES controllers(id) ON DELETE RESTRICT,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE RESTRICT
);

CREATE TABLE customers (
    id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (controller_id) REFERENCES controllers(id) ON DELETE RESTRICT
);

ALTER TABLE instances ADD COLUMN controller_id TEXT;
ALTER TABLE instances ADD COLUMN agent_id TEXT;
ALTER TABLE instances ADD COLUMN customer_id TEXT;

-- Legacy instances have no reliable ownership chain. They are intentionally
-- removed instead of being assigned to fabricated customers or agents.
DELETE FROM instances;

CREATE TRIGGER controllers_require_controller_node_insert
BEFORE INSERT ON controllers
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM nodes WHERE id = NEW.node_id AND role IN ('controller', 'hybrid')
    ) THEN RAISE(ABORT, 'controller_requires_controller_node') END;
END;

CREATE TRIGGER agents_require_agent_node_insert
BEFORE INSERT ON agents
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM nodes WHERE id = NEW.node_id AND role IN ('agent', 'hybrid')
    ) THEN RAISE(ABORT, 'agent_requires_agent_node') END;
END;

CREATE TRIGGER instances_require_ownership_insert
BEFORE INSERT ON instances
BEGIN
    SELECT CASE WHEN NEW.controller_id IS NULL OR NEW.agent_id IS NULL OR NEW.customer_id IS NULL
        THEN RAISE(ABORT, 'instance_requires_controller_agent_customer') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM agents
        WHERE id = NEW.agent_id AND controller_id = NEW.controller_id AND node_id = NEW.node_id
    ) THEN RAISE(ABORT, 'instance_agent_controller_mismatch') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM customers WHERE id = NEW.customer_id AND controller_id = NEW.controller_id
    ) THEN RAISE(ABORT, 'instance_customer_controller_mismatch') END;
END;

CREATE TRIGGER instances_require_ownership_update
BEFORE UPDATE OF controller_id, agent_id, customer_id, node_id ON instances
BEGIN
    SELECT CASE WHEN NEW.controller_id IS NULL OR NEW.agent_id IS NULL OR NEW.customer_id IS NULL
        THEN RAISE(ABORT, 'instance_requires_controller_agent_customer') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM agents
        WHERE id = NEW.agent_id AND controller_id = NEW.controller_id AND node_id = NEW.node_id
    ) THEN RAISE(ABORT, 'instance_agent_controller_mismatch') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM customers WHERE id = NEW.customer_id AND controller_id = NEW.controller_id
    ) THEN RAISE(ABORT, 'instance_customer_controller_mismatch') END;
END;

CREATE TRIGGER controllers_restrict_delete
BEFORE DELETE ON controllers
WHEN EXISTS (SELECT 1 FROM agents WHERE controller_id = OLD.id)
  OR EXISTS (SELECT 1 FROM customers WHERE controller_id = OLD.id)
  OR EXISTS (SELECT 1 FROM instances WHERE controller_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'controller_has_dependents');
END;

CREATE TRIGGER agents_restrict_delete
BEFORE DELETE ON agents
WHEN EXISTS (SELECT 1 FROM instances WHERE agent_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'agent_has_instances');
END;

CREATE TRIGGER customers_restrict_delete
BEFORE DELETE ON customers
WHEN EXISTS (SELECT 1 FROM instances WHERE customer_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'customer_has_instances');
END;

CREATE INDEX idx_agents_controller ON agents(controller_id);
CREATE INDEX idx_customers_controller ON customers(controller_id);
CREATE INDEX idx_instances_ownership ON instances(controller_id, agent_id, customer_id);
