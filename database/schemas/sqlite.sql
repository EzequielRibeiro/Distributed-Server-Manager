-- Capivara DSM complete schema v41 - new installations only
-- source: 001_initial.sql
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('controller', 'agent', 'hybrid')),
    status TEXT NOT NULL DEFAULT 'pending',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS instances (
    id TEXT PRIMARY KEY,
    node_id TEXT,
    game_id TEXT NOT NULL,
    edition TEXT,
    runtime_id TEXT,
    version TEXT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    manifest_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    node_id TEXT,
    instance_id TEXT,
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE SET NULL,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    source TEXT NOT NULL,
    node_id TEXT,
    instance_id TEXT,
    operation_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE SET NULL,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE SET NULL,
    FOREIGN KEY (operation_id) REFERENCES operations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS content_installations (
    instance_id TEXT NOT NULL,
    content_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'installed',
    lock_path TEXT,
    installed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (instance_id, content_id),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_instances_node_game
    ON instances(node_id, game_id);
CREATE INDEX IF NOT EXISTS idx_operations_status_created
    ON operations(status, created_at);
CREATE INDEX IF NOT EXISTS idx_events_created
    ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_instance_created
    ON events(instance_id, created_at);
CREATE INDEX IF NOT EXISTS idx_content_instance_status
    ON content_installations(instance_id, status);

-- source: 002_operational_persistence.sql
CREATE TABLE IF NOT EXISTS state_imports (
    source_path TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    checksum TEXT NOT NULL,
    records_imported INTEGER NOT NULL DEFAULT 0,
    source_updated_at TEXT,
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_events_type_created
    ON events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_events_severity_created
    ON events(severity, created_at);
CREATE INDEX IF NOT EXISTS idx_operations_type_created
    ON operations(operation_type, created_at);
CREATE INDEX IF NOT EXISTS idx_operations_instance_created
    ON operations(instance_id, created_at);
CREATE INDEX IF NOT EXISTS idx_state_imports_kind_imported
    ON state_imports(source_kind, imported_at);

-- source: 003_controller_agent_customer_model.sql
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

-- source: 004_instance_service_contracts.sql
CREATE TABLE service_contracts (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    game_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending','active','suspended','cancelled','expired')),
    instance_limit INTEGER NOT NULL DEFAULT 1 CHECK (instance_limit > 0),
    starts_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ends_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
);

CREATE TABLE instance_contracts (
    instance_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (contract_id) REFERENCES service_contracts(id) ON DELETE RESTRICT
);

-- Preserve existing valid instances by assigning a one-instance legacy contract.
INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit,metadata_json)
SELECT CASE WHEN id='cliente-demo' AND customer_id='CLI-DEMO-001' THEN 'aurora-minecraft-001' ELSE 'legacy-' || id END,
       customer_id,game_id,'active',1,
       CASE WHEN id='cliente-demo' AND customer_id='CLI-DEMO-001' THEN '{"demo":true,"service":"Minecraft"}' ELSE '{"origin":"migration"}' END
FROM instances;

INSERT INTO instance_contracts(instance_id,contract_id)
SELECT id,CASE WHEN id='cliente-demo' AND customer_id='CLI-DEMO-001' THEN 'aurora-minecraft-001' ELSE 'legacy-' || id END
FROM instances;

-- Fictitious Aurora contract available for the customer creation flow.
INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit,metadata_json)
SELECT 'aurora-dayz-001','CLI-DEMO-001','dayz','active',1,'{"demo":true,"service":"DayZ"}'
WHERE EXISTS (SELECT 1 FROM customers WHERE id='CLI-DEMO-001');

CREATE TRIGGER instance_contract_matches_insert
BEFORE INSERT ON instance_contracts
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM instances i JOIN service_contracts c ON c.id=NEW.contract_id
        WHERE i.id=NEW.instance_id AND i.customer_id=c.customer_id AND i.game_id=c.game_id
          AND c.status='active' AND (c.ends_at IS NULL OR c.ends_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ) THEN RAISE(ABORT, 'instance_contract_mismatch') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM instance_contracts WHERE contract_id=NEW.contract_id
    ) >= (SELECT instance_limit FROM service_contracts WHERE id=NEW.contract_id)
    THEN RAISE(ABORT, 'contract_instance_limit_reached') END;
END;

CREATE TRIGGER instances_require_contract_before_active
BEFORE UPDATE OF status ON instances
WHEN NEW.status NOT IN ('pending','provisioning') AND NOT EXISTS (
    SELECT 1 FROM instance_contracts WHERE instance_id=NEW.id
)
BEGIN
    SELECT RAISE(ABORT, 'instance_requires_service_contract');
END;

CREATE INDEX idx_service_contracts_customer_status ON service_contracts(customer_id,status);
CREATE INDEX idx_instance_contracts_contract ON instance_contracts(contract_id);

-- source: 005_dashboard_users.sql
CREATE TABLE dashboard_users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','controller','customer','operator')),
    scope_id TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE instance_access (
    username TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    permission_profile TEXT NOT NULL DEFAULT 'viewer'
        CHECK (permission_profile IN ('viewer','operator','manager')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (username, instance_id),
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    instance_id TEXT,
    action TEXT NOT NULL,
    result TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_dashboard_users_role_scope
    ON dashboard_users(role, scope_id, active);
CREATE INDEX idx_audit_log_instance_created
    ON audit_log(instance_id, created_at);

-- source: 006_customer_administration.sql
-- source: 007_customer_billing_and_identity.sql
-- =============================================================
-- Capivara DSM
-- Migration 007
-- Customer identity and external billing integration
-- =============================================================

ALTER TABLE customers
    ADD COLUMN legal_name TEXT;

ALTER TABLE customers
    ADD COLUMN document_type TEXT
        CHECK (
            document_type IS NULL
            OR document_type IN ('cpf', 'cnpj', 'other')
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
    ADD COLUMN billing_synced_at TEXT;

CREATE INDEX idx_customers_document
    ON customers(document_type, document_number);

CREATE INDEX idx_customers_billing
    ON customers(billing_provider, billing_customer_id);

CREATE INDEX idx_customers_billing_status
    ON customers(billing_status);

-- source: 008_instance_runtime_selection.sql
-- =============================================================
-- Capivara DSM
-- Migration 008
-- Instance runtime selection metadata
-- =============================================================
-- Migration 001 already creates edition, runtime_id and version.
-- Dashboard provisioning additionally persists the fields below.
-- Keep migration history additive: do not recreate columns owned by 001.

ALTER TABLE instances ADD COLUMN variant TEXT;
ALTER TABLE instances ADD COLUMN game_version TEXT;
ALTER TABLE instances ADD COLUMN build_id TEXT;

-- source: 009_instance_network_ports.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 009
-- Instance network port reservations
-- =============================================================

CREATE TABLE instance_ports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    instance_id TEXT NOT NULL,
    node_id TEXT NOT NULL,

    name TEXT NOT NULL,

    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'udp')),

    port INTEGER NOT NULL
        CHECK (port BETWEEN 1 AND 65535),

    bind_address TEXT NOT NULL DEFAULT '0.0.0.0',

    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE CASCADE,

    FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE CASCADE,

    UNIQUE (instance_id, name, protocol),

    UNIQUE (node_id, protocol, port)
);

CREATE INDEX idx_instance_ports_instance
    ON instance_ports(instance_id);

CREATE INDEX idx_instance_ports_node
    ON instance_ports(node_id);

CREATE INDEX idx_instance_ports_node_protocol_port
    ON instance_ports(node_id, protocol, port);

-- source: 010_alert_persistence.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 010
-- Alert persistence
--
-- Persistência relacional do sistema de alertas.
--
-- alerts:
--   mantém o estado atual de cada alerta.
--
-- alert_events:
--   mantém o histórico imutável das transições do alerta.
-- =============================================================


-- =============================================================
-- ALERTS
-- =============================================================

CREATE TABLE alerts (
    id TEXT PRIMARY KEY,

    scope TEXT NOT NULL
        CHECK (
            scope IN (
                'controller',
                'agent',
                'node',
                'instance'
            )
        ),

    controller_id TEXT,
    agent_id TEXT,
    node_id TEXT,
    instance_id TEXT,

    rule_id TEXT NOT NULL,

    level TEXT NOT NULL
        CHECK (
            level IN (
                'INFO',
                'WARNING',
                'CRITICAL'
            )
        ),

    state TEXT NOT NULL
        CHECK (
            state IN (
                'OPEN',
                'ACKNOWLEDGED',
                'RESOLVED',
                'SUPPRESSED'
            )
        ),

    message TEXT NOT NULL,

    opened_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    acknowledged_at TEXT,
    resolved_at TEXT,
    suppressed_until TEXT,

    FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE RESTRICT,

    FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE RESTRICT,

    FOREIGN KEY (node_id)
        REFERENCES nodes(id)
        ON DELETE RESTRICT,

    FOREIGN KEY (instance_id)
        REFERENCES instances(id)
        ON DELETE RESTRICT
);


-- =============================================================
-- ALERT EVENTS
-- =============================================================

CREATE TABLE alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    alert_id TEXT NOT NULL,

    action TEXT NOT NULL
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

    level TEXT NOT NULL
        CHECK (
            level IN (
                'INFO',
                'WARNING',
                'CRITICAL'
            )
        ),

    old_state TEXT,

    new_state TEXT NOT NULL
        CHECK (
            new_state IN (
                'OPEN',
                'ACKNOWLEDGED',
                'RESOLVED',
                'SUPPRESSED'
            )
        ),

    message TEXT NOT NULL,

    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    FOREIGN KEY (alert_id)
        REFERENCES alerts(id)
        ON DELETE CASCADE
);

-- =============================================================
-- ALERT SCOPE INTEGRITY
-- =============================================================

CREATE TRIGGER alerts_validate_scope_insert
BEFORE INSERT ON alerts
BEGIN
    SELECT CASE
        WHEN NEW.scope = 'controller'
             AND NEW.controller_id IS NULL
        THEN RAISE(ABORT, 'alert_controller_scope_requires_controller')
    END;

    SELECT CASE
        WHEN NEW.scope = 'agent'
             AND (NEW.controller_id IS NULL OR NEW.agent_id IS NULL)
        THEN RAISE(ABORT, 'alert_agent_scope_requires_controller_agent')
    END;

    SELECT CASE
        WHEN NEW.scope = 'node'
             AND (NEW.controller_id IS NULL OR NEW.node_id IS NULL)
        THEN RAISE(ABORT, 'alert_node_scope_requires_controller_node')
    END;

    SELECT CASE
        WHEN NEW.scope = 'instance'
             AND (
                 NEW.controller_id IS NULL
                 OR NEW.agent_id IS NULL
                 OR NEW.node_id IS NULL
                 OR NEW.instance_id IS NULL
             )
        THEN RAISE(
            ABORT,
            'alert_instance_scope_requires_controller_agent_node_instance'
        )
    END;

    SELECT CASE
        WHEN NEW.agent_id IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1
                 FROM agents
                 WHERE id = NEW.agent_id
                   AND controller_id = NEW.controller_id
             )
        THEN RAISE(ABORT, 'alert_agent_controller_mismatch')
    END;

    SELECT CASE
        WHEN NEW.instance_id IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1
                 FROM instances
                 WHERE id = NEW.instance_id
                   AND controller_id = NEW.controller_id
                   AND agent_id = NEW.agent_id
                   AND node_id = NEW.node_id
             )
        THEN RAISE(ABORT, 'alert_instance_ownership_mismatch')
    END;
END;


CREATE TRIGGER alerts_validate_scope_update
BEFORE UPDATE OF
    scope,
    controller_id,
    agent_id,
    node_id,
    instance_id
ON alerts
BEGIN
    SELECT CASE
        WHEN NEW.scope = 'controller'
             AND NEW.controller_id IS NULL
        THEN RAISE(ABORT, 'alert_controller_scope_requires_controller')
    END;

    SELECT CASE
        WHEN NEW.scope = 'agent'
             AND (NEW.controller_id IS NULL OR NEW.agent_id IS NULL)
        THEN RAISE(ABORT, 'alert_agent_scope_requires_controller_agent')
    END;

    SELECT CASE
        WHEN NEW.scope = 'node'
             AND (NEW.controller_id IS NULL OR NEW.node_id IS NULL)
        THEN RAISE(ABORT, 'alert_node_scope_requires_controller_node')
    END;

    SELECT CASE
        WHEN NEW.scope = 'instance'
             AND (
                 NEW.controller_id IS NULL
                 OR NEW.agent_id IS NULL
                 OR NEW.node_id IS NULL
                 OR NEW.instance_id IS NULL
             )
        THEN RAISE(
            ABORT,
            'alert_instance_scope_requires_controller_agent_node_instance'
        )
    END;

    SELECT CASE
        WHEN NEW.agent_id IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1
                 FROM agents
                 WHERE id = NEW.agent_id
                   AND controller_id = NEW.controller_id
             )
        THEN RAISE(ABORT, 'alert_agent_controller_mismatch')
    END;

    SELECT CASE
        WHEN NEW.instance_id IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1
                 FROM instances
                 WHERE id = NEW.instance_id
                   AND controller_id = NEW.controller_id
                   AND agent_id = NEW.agent_id
                   AND node_id = NEW.node_id
             )
        THEN RAISE(ABORT, 'alert_instance_ownership_mismatch')
    END;
END;

-- =============================================================
-- INDEXES — ALERTS
-- =============================================================

-- =============================================================
-- ACTIVE ALERT DEDUPLICATION
-- =============================================================
--
-- Uma mesma regra pode possuir no máximo um alerta não resolvido
-- para o mesmo alvo lógico.
--
-- A deduplicação é separada por scope porque os identificadores
-- não aplicáveis aos scopes superiores permanecem NULL.
--
-- RESOLVED não participa da restrição, permitindo que uma nova
-- ocorrência da mesma regra seja aberta futuramente.
--

CREATE UNIQUE INDEX idx_alerts_active_controller
    ON alerts(
        rule_id,
        controller_id
    )
    WHERE
        scope = 'controller'
        AND state <> 'RESOLVED';


CREATE UNIQUE INDEX idx_alerts_active_agent
    ON alerts(
        rule_id,
        controller_id,
        agent_id
    )
    WHERE
        scope = 'agent'
        AND state <> 'RESOLVED';


CREATE UNIQUE INDEX idx_alerts_active_node
    ON alerts(
        rule_id,
        controller_id,
        node_id
    )
    WHERE
        scope = 'node'
        AND state <> 'RESOLVED';


CREATE UNIQUE INDEX idx_alerts_active_instance
    ON alerts(
        rule_id,
        controller_id,
        agent_id,
        node_id,
        instance_id
    )
    WHERE
        scope = 'instance'
        AND state <> 'RESOLVED';

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
    ON alerts(scope, state);


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
-- Migration 011
-- Agent managed network port ranges
-- =============================================================

CREATE TABLE agent_port_ranges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    agent_id TEXT NOT NULL,

    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'udp')),

    start_port INTEGER NOT NULL
        CHECK (start_port BETWEEN 1 AND 65535),

    end_port INTEGER NOT NULL
        CHECK (end_port BETWEEN 1 AND 65535),

    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),

    label TEXT,

    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),

    CHECK (start_port <= end_port),

    FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,

    UNIQUE (
        agent_id,
        protocol,
        start_port,
        end_port
    )
);

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

-- Compatibilidade com a política anterior.
-- A faixa pode ser alterada posteriormente pelo administrador.
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

-- Todo Agent criado depois da migration também recebe um
-- pool inicial administrável pelo Controller.
CREATE TRIGGER agents_default_port_ranges_insert
AFTER INSERT ON agents
BEGIN
    INSERT INTO agent_port_ranges(
        agent_id,
        protocol,
        start_port,
        end_port,
        status,
        label
    )
    VALUES (
        NEW.id,
        'udp',
        24000,
        24999,
        'active',
        'default'
    );

    INSERT INTO agent_port_ranges(
        agent_id,
        protocol,
        start_port,
        end_port,
        status,
        label
    )
    VALUES (
        NEW.id,
        'tcp',
        24000,
        24999,
        'active',
        'default'
    );
END;

-- source: 012_location_topology.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 012
-- Geographic regions, datacenters and Agent placement
-- =============================================================

CREATE TABLE regions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT,
    continent_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

CREATE TABLE datacenters (
    id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT,
    city TEXT,
    country_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (region_id)
        REFERENCES regions(id)
        ON DELETE RESTRICT
);

CREATE TABLE agent_locations (
    agent_id TEXT PRIMARY KEY,
    datacenter_id TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    public_host TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,
    FOREIGN KEY (datacenter_id)
        REFERENCES datacenters(id)
        ON DELETE RESTRICT
);

CREATE TABLE controller_placement_policies (
    controller_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'latency_assisted'
        CHECK (mode IN (
            'controller',
            'customer_region',
            'latency_assisted'
        )),
    customer_region_selection INTEGER NOT NULL DEFAULT 1
        CHECK (customer_region_selection IN (0, 1)),
    cross_region_fallback INTEGER NOT NULL DEFAULT 0
        CHECK (cross_region_fallback IN (0, 1)),
    max_latency_ms INTEGER,
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

CREATE INDEX idx_datacenters_region
    ON datacenters(region_id, status);

CREATE INDEX idx_agent_locations_datacenter
    ON agent_locations(datacenter_id, status);

-- source: 013_controller_placement_policy_fk.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 013
-- Enforce Controller ownership for placement policies
-- =============================================================
CREATE TABLE controller_placement_policies_new (
    controller_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'latency_assisted'
        CHECK (mode IN (
            'controller',
            'customer_region',
            'latency_assisted'
        )),
    customer_region_selection INTEGER NOT NULL DEFAULT 1
        CHECK (customer_region_selection IN (0, 1)),
    cross_region_fallback INTEGER NOT NULL DEFAULT 0
        CHECK (cross_region_fallback IN (0, 1)),
    max_latency_ms INTEGER,
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    FOREIGN KEY (controller_id)
        REFERENCES controllers(id)
        ON DELETE CASCADE
);
INSERT INTO controller_placement_policies_new (
    controller_id,
    mode,
    customer_region_selection,
    cross_region_fallback,
    max_latency_ms,
    updated_at
)
SELECT
    controller_id,
    mode,
    customer_region_selection,
    cross_region_fallback,
    max_latency_ms,
    updated_at
FROM controller_placement_policies;
DROP TABLE controller_placement_policies;
ALTER TABLE controller_placement_policies_new
    RENAME TO controller_placement_policies;

-- source: 014_customer_account_identity.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 014
-- Customer self-service account identity and SFTP username
-- =============================================================

ALTER TABLE customers
    ADD COLUMN account_email TEXT;

ALTER TABLE customers
    ADD COLUMN sftp_username TEXT;

ALTER TABLE customers
    ADD COLUMN registration_status TEXT NOT NULL DEFAULT 'managed'
        CHECK (registration_status IN (
            'managed',
            'pending',
            'active',
            'disabled'
        ));

ALTER TABLE customers
    ADD COLUMN email_verified_at TEXT;

CREATE UNIQUE INDEX idx_customers_account_email
    ON customers(LOWER(account_email))
    WHERE account_email IS NOT NULL;

CREATE UNIQUE INDEX idx_customers_sftp_username
    ON customers(sftp_username)
    WHERE sftp_username IS NOT NULL;

-- source: 015_customer_account_access.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 015
-- Customer account members and password recovery
-- =============================================================

CREATE TABLE customer_account_members (
    customer_id TEXT NOT NULL,
    username TEXT NOT NULL,
    account_role TEXT NOT NULL DEFAULT 'member'
        CHECK (account_role IN ('owner','manager','member')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (customer_id, username),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_customer_account_owner
    ON customer_account_members(customer_id)
    WHERE account_role='owner';

CREATE TABLE customer_password_recovery (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);

CREATE INDEX idx_customer_password_recovery_user
    ON customer_password_recovery(username, expires_at);

-- source: 016_customer_account_integrity.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 016 - customer_account integrity parity
-- SQLite already enforces a single owner through migration 015.
-- Add the role lookup index present in the MySQL model.
-- =============================================================
CREATE INDEX IF NOT EXISTS idx_customer_account_member_role
    ON customer_account_members(customer_id, account_role);

-- source: 017_customer_user_identity_and_invitations.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 017 - per-login e-mail identity and team invitations
-- =============================================================
CREATE TABLE customer_user_identities (
    username TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    email_verified_at TEXT,
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);
CREATE UNIQUE INDEX idx_customer_user_identity_email
    ON customer_user_identities(LOWER(email));

-- Backfill the verified/contact e-mail for existing Customer owners.
INSERT INTO customer_user_identities(username,email,email_verified_at)
SELECT m.username,c.account_email,c.email_verified_at
FROM customer_account_members m
JOIN customers c ON c.id=m.customer_id
WHERE m.account_role='owner'
  AND c.account_email IS NOT NULL;

CREATE TABLE customer_invitations (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    email TEXT NOT NULL,
    account_role TEXT NOT NULL CHECK (account_role IN ('manager','member')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    revoked_at TEXT,
    invited_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (invited_by) REFERENCES dashboard_users(username) ON DELETE RESTRICT
);
CREATE INDEX idx_customer_invitations_customer
    ON customer_invitations(customer_id, created_at);
CREATE INDEX idx_customer_invitations_email
    ON customer_invitations(email, expires_at);

CREATE TABLE customer_invitation_access (
    invitation_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    permission_profile TEXT NOT NULL CHECK (permission_profile IN ('viewer','operator','manager')),
    PRIMARY KEY (invitation_id, instance_id),
    FOREIGN KEY (invitation_id) REFERENCES customer_invitations(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

-- source: 018_customer_email_verification.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 018 - one-time e-mail verification tokens
-- =============================================================
CREATE TABLE customer_email_verification (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (username) REFERENCES dashboard_users(username) ON DELETE CASCADE
);
CREATE INDEX idx_customer_email_verification_user
    ON customer_email_verification(username, expires_at);

-- source: 019_customer_account_legacy_backfill.sql
-- =============================================================
-- Capivara Distributed Server Manager
-- Migration 019
-- Legacy customer account membership and identity backfill
--
-- Purpose:
--   Migrate customer users created before the customer-account
--   membership model introduced by migration 015.
--
-- Rules:
--   - Never replace an existing account owner.
--   - Never duplicate an existing membership.
--   - Only customer users whose scope_id matches customers.id
--     are considered.
--   - Backfill the per-login identity only when an account
--     e-mail exists and the username has no identity yet.
-- =============================================================

-- -------------------------------------------------------------
-- 1. Restore missing legacy customer ownership.
--
-- A legacy customer user becomes owner only when:
--   * it belongs to the customer through scope_id;
--   * it has no membership yet;
--   * that customer has no owner yet.
--
-- The NOT EXISTS checks make this safe for databases where
-- migrations 015-018 have already been partially populated.
-- -------------------------------------------------------------

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
      FROM customer_account_members owner
      WHERE owner.customer_id = c.id
        AND owner.account_role = 'owner'
  );


-- -------------------------------------------------------------
-- 2. Restore the login identity for customer owners.
--
-- Migration 017 originally performed this operation, but legacy
-- users without a membership were not visible to that backfill.
--
-- Only accounts with an account_email are considered.
-- Existing identities are preserved.
-- -------------------------------------------------------------

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

-- source: 020_agent_runtime_inventory.sql
-- Capivara DSM - Migration 020
-- Agent runtime inventory and heartbeat health are intentionally separated
-- from agents.status (administrative/lifecycle state).

CREATE TABLE agent_runtime_inventory (
    agent_id TEXT PRIMARY KEY,
    hostname TEXT,
    os_name TEXT,
    architecture TEXT,
    capivara_version TEXT,
    address TEXT,
    fingerprint TEXT,
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    cpu_json TEXT NOT NULL DEFAULT '{}',
    ram_total_bytes INTEGER,
    storage_json TEXT NOT NULL DEFAULT '{}',
    health_status TEXT NOT NULL DEFAULT 'offline'
        CHECK (health_status IN ('online', 'degraded', 'offline')),
    last_seen TEXT,
    heartbeat_interval_seconds INTEGER NOT NULL DEFAULT 30,
    degraded_after_seconds INTEGER NOT NULL DEFAULT 60,
    offline_after_seconds INTEGER NOT NULL DEFAULT 120,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CHECK (heartbeat_interval_seconds > 0),
    CHECK (degraded_after_seconds >= heartbeat_interval_seconds),
    CHECK (offline_after_seconds > degraded_after_seconds)
);

CREATE INDEX idx_agent_runtime_health
    ON agent_runtime_inventory(health_status, last_seen);

CREATE INDEX idx_agent_runtime_fingerprint
    ON agent_runtime_inventory(fingerprint);

-- source: 021_agent_secure_pairing.sql
-- Capivara DSM - Migration 021
-- Secure Controller <-> Agent enrollment.
-- Pairing tokens and permanent Agent secrets are stored only as hashes.

CREATE TABLE agent_pairing_tokens (
    id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (controller_id) REFERENCES controllers(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_pairing_tokens_controller
    ON agent_pairing_tokens(controller_id, expires_at, consumed_at);

CREATE TABLE agent_credentials (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    controller_id TEXT NOT NULL,
    credential_type TEXT NOT NULL DEFAULT 'opaque-v1',
    secret_hash TEXT,
    fingerprint TEXT NOT NULL,
    public_key TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked')),
    issued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_used_at TEXT,
    revoked_at TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (controller_id) REFERENCES controllers(id) ON DELETE CASCADE,
    UNIQUE (agent_id, id)
);

CREATE INDEX idx_agent_credentials_agent
    ON agent_credentials(agent_id, status);

CREATE INDEX idx_agent_credentials_fingerprint
    ON agent_credentials(fingerprint, status);

-- source: 022_agent_installation_tracking.sql
ALTER TABLE agent_pairing_tokens ADD COLUMN platform TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN install_method TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN region_id TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN datacenter_id TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN agent_id TEXT;

CREATE INDEX IF NOT EXISTS idx_agent_pairing_tokens_agent_id
    ON agent_pairing_tokens(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_pairing_tokens_datacenter_id
    ON agent_pairing_tokens(datacenter_id);

-- source: 023_agent_network_inventory.sql
ALTER TABLE agent_runtime_inventory ADD COLUMN network_json TEXT NOT NULL DEFAULT '{}';

-- source: 024_agent_remote_updates.sql
-- Capivara DSM - Migration 024
-- Remote Agent update state and safe rollout coordination.

CREATE TABLE agent_update_state (
    agent_id TEXT PRIMARY KEY,
    installed_version TEXT,
    available_version TEXT,
    update_channel TEXT NOT NULL DEFAULT 'stable'
        CHECK (update_channel IN ('stable','beta','local/manual')),
    desired_version TEXT,
    update_status TEXT NOT NULL DEFAULT 'idle'
        CHECK (update_status IN ('idle','planned','updating','verifying','completed','failed')),
    rollout_id TEXT,
    batch_number INTEGER,
    batch_position INTEGER,
    requested_at TEXT,
    last_update TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_update_rollout
    ON agent_update_state(rollout_id,batch_number,batch_position);

CREATE INDEX idx_agent_update_status
    ON agent_update_state(update_status,update_channel);

-- source: 025_agent_game_data_jobs.sql
-- Capivara DSM - Migration 025
-- Agent-owned game-data command queue.

CREATE TABLE agent_game_data_jobs (
    job_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (action IN ('install','update','verify')),
    environment_id TEXT NOT NULL,
    selector TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','delivered','running','completed','failed')),
    progress INTEGER NOT NULL DEFAULT 0
        CHECK (progress >= 0 AND progress <= 100),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_game_data_jobs_agent_status
    ON agent_game_data_jobs(agent_id,status,created_at);

CREATE INDEX idx_agent_game_data_jobs_environment
    ON agent_game_data_jobs(agent_id,environment_id,status);

-- source: 026_agent_installation_preconfiguration.sql
-- Capivara DSM - Migration 026
-- Preconfiguration attached to an Agent installation before enrollment.
-- 025 is intentionally reserved by the open Agent game-data orchestration work.

CREATE TABLE agent_installation_preconfiguration (
    installation_id TEXT PRIMARY KEY,
    requested_name TEXT,
    port_protocol TEXT
        CHECK (port_protocol IN ('tcp','udp','both')),
    port_start INTEGER,
    port_end INTEGER,
    applied_at TEXT,
    apply_error TEXT,
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    updated_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    CHECK (
        (port_start IS NULL AND port_end IS NULL AND port_protocol IS NULL)
        OR
        (port_start BETWEEN 1 AND 65535
         AND port_end BETWEEN port_start AND 65535
         AND port_protocol IS NOT NULL)
    ),
    FOREIGN KEY (installation_id)
        REFERENCES agent_pairing_tokens(id)
        ON DELETE CASCADE
);

CREATE INDEX idx_agent_install_preconfig_applied
    ON agent_installation_preconfiguration(applied_at, apply_error);

-- source: 027_agent_instance_runtime_commands.sql
CREATE TABLE agent_instance_commands (
    command_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('status','doctor')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_instance_commands_agent_status
    ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance
    ON agent_instance_commands(instance_id,created_at);

-- source: 028_agent_instance_lifecycle_actions.sql
-- Capivara DSM - Migration 028 - SQLite
-- Expand the immutable B6 observation queue to game-agnostic lifecycle actions.

CREATE TABLE agent_instance_commands_v2 (
    command_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('status','doctor','start','stop','restart')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

INSERT INTO agent_instance_commands_v2
SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,
       created_at,delivered_at,completed_at,updated_at
FROM agent_instance_commands;

DROP TABLE agent_instance_commands;
ALTER TABLE agent_instance_commands_v2 RENAME TO agent_instance_commands;

CREATE INDEX idx_agent_instance_commands_agent_status
    ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance
    ON agent_instance_commands(instance_id,created_at);

-- source: 029_agent_instance_provisioning.sql
-- Capivara DSM - Migration 029 - SQLite
-- B10 persistent Controller -> Agent instance provisioning pipeline.

CREATE TABLE agent_instance_provisioning (
    provisioning_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    selector TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','delivered','running','completed','failed')),
    current_step TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_instance_provisioning_agent_status
    ON agent_instance_provisioning(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_provisioning_instance
    ON agent_instance_provisioning(instance_id,created_at);

-- source: 030_agent_instance_reconciliation.sql
-- Capivara DSM - Migration 030 - SQLite
-- Controller-side projection of Agent runtime reconciliation state.

CREATE TABLE agent_instance_reconciliation (
    instance_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    desired_state TEXT,
    observed_state TEXT,
    reconcile_status TEXT NOT NULL DEFAULT 'unknown',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_success_at TEXT,
    next_retry_at TEXT,
    last_error TEXT,
    drift TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_instance_reconciliation_agent_status
    ON agent_instance_reconciliation(agent_id,reconcile_status,updated_at);

-- source: 031_agent_instance_runtime_health.sql
-- Capivara DSM - Migration 031 - SQLite
-- Final Controller-side instance runtime health projection.

CREATE TABLE agent_instance_runtime_health (
    instance_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    desired_state TEXT,
    observed_state TEXT,
    reconcile_status TEXT NOT NULL DEFAULT 'unknown',
    health TEXT NOT NULL DEFAULT 'unknown',
    operation_status TEXT NOT NULL DEFAULT 'idle',
    operation_name TEXT,
    last_error TEXT,
    last_transition_at TEXT,
    reported_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_agent_instance_runtime_health_agent
    ON agent_instance_runtime_health(agent_id,health,updated_at);

-- source: 032_universal_events.sql
-- Capivara DSM - Migration 032 - SQLite
-- Durable normalized store for the Universal Event Platform.
-- Subject identifiers intentionally have no foreign keys: immutable event history
-- must survive deletion or re-creation of mutable infrastructure entities.

CREATE TABLE universal_events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source TEXT NOT NULL,
    source_id TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    agent_id TEXT,
    instance_id TEXT,
    correlation_id TEXT,
    causation_id TEXT,
    actor_type TEXT,
    actor_id TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_universal_events_type_time
    ON universal_events(event_type, occurred_at);
CREATE INDEX idx_universal_events_agent_time
    ON universal_events(agent_id, occurred_at);
CREATE INDEX idx_universal_events_instance_time
    ON universal_events(instance_id, occurred_at);
CREATE INDEX idx_universal_events_severity_time
    ON universal_events(severity, occurred_at);
CREATE INDEX idx_universal_events_correlation
    ON universal_events(correlation_id, occurred_at);

-- source: 033_universal_configuration.sql
-- Capivara DSM - Migration 033 - SQLite
-- Universal Configuration Platform.

CREATE TABLE configurations (
    configuration_id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global','agent','instance')),
    scope_key TEXT NOT NULL,
    namespace TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(scope_type, scope_key, namespace)
);

CREATE TABLE configuration_revisions (
    configuration_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(configuration_id, revision)
);

CREATE TABLE agent_configuration_state (
    agent_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('agent','instance')),
    target_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    desired_revision TEXT NOT NULL,
    applied_revision TEXT,
    desired_checksum TEXT NOT NULL,
    applied_checksum TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    reported_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(agent_id, target_type, target_id, namespace),
    FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_configurations_scope_namespace
    ON configurations(scope_type, scope_key, namespace);
CREATE INDEX idx_configuration_revisions_created
    ON configuration_revisions(configuration_id, revision DESC);
CREATE INDEX idx_agent_configuration_state_pending
    ON agent_configuration_state(agent_id, status, target_type, target_id, namespace);

-- source: 034_universal_observability.sql
-- Capivara DSM - Migration 034 - SQLite
-- Universal Observability Platform.

CREATE TABLE observability_samples (
    sample_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('agent','instance')),
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL CHECK (metric_type IN ('gauge','counter')),
    value_double REAL NOT NULL,
    unit TEXT NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    collected_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE observability_latest (
    agent_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    dimensions_key TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    value_double REAL NOT NULL,
    unit TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(agent_id, subject_key, metric_name, dimensions_key)
);

CREATE INDEX idx_observability_samples_agent_time ON observability_samples(agent_id, collected_at DESC);
CREATE INDEX idx_observability_samples_instance_time ON observability_samples(instance_id, collected_at DESC);
CREATE INDEX idx_observability_samples_metric_time ON observability_samples(metric_name, collected_at DESC);
CREATE INDEX idx_observability_latest_agent ON observability_latest(agent_id, subject_key, metric_name);

-- source: 035_universal_content.sql
-- Capivara DSM - Migration 035 - SQLite
CREATE TABLE content_assignments (
 assignment_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, agent_id TEXT NOT NULL,
 content_id TEXT NOT NULL, game_id TEXT NOT NULL, content_type TEXT NOT NULL,
 desired_state TEXT NOT NULL CHECK(desired_state IN ('installed','absent')),
 version TEXT NOT NULL, provider TEXT NOT NULL, target TEXT NOT NULL,
 artifact_json TEXT NOT NULL DEFAULT '{}', dependencies_json TEXT NOT NULL DEFAULT '[]', conflicts_json TEXT NOT NULL DEFAULT '[]',
 revision INTEGER NOT NULL, checksum TEXT NOT NULL, requested_by TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(instance_id,content_id)
);
CREATE TABLE content_assignment_revisions (
 assignment_id TEXT NOT NULL, revision INTEGER NOT NULL, desired_state TEXT NOT NULL,
 version TEXT NOT NULL, provider TEXT NOT NULL, target TEXT NOT NULL, artifact_json TEXT NOT NULL,
 dependencies_json TEXT NOT NULL, conflicts_json TEXT NOT NULL, checksum TEXT NOT NULL,
 requested_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY(assignment_id,revision)
);
CREATE TABLE agent_content_state (
 agent_id TEXT NOT NULL, instance_id TEXT NOT NULL, content_id TEXT NOT NULL,
 desired_revision INTEGER NOT NULL, applied_revision INTEGER, desired_checksum TEXT NOT NULL, applied_checksum TEXT,
 status TEXT NOT NULL, installed_version TEXT, last_error TEXT, reported_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(agent_id,instance_id,content_id)
);
CREATE INDEX idx_content_assignments_agent ON content_assignments(agent_id,instance_id,desired_state);
CREATE INDEX idx_agent_content_state_agent ON agent_content_state(agent_id,status);

-- source: 036_universal_smart_backup.sql
CREATE TABLE IF NOT EXISTS backup_policies (
 policy_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL UNIQUE, agent_id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 mode TEXT NOT NULL, consistency TEXT NOT NULL, compression TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
 retention_count INTEGER NOT NULL, include_json TEXT NOT NULL DEFAULT '[]', exclude_json TEXT NOT NULL DEFAULT '[]',
 revision INTEGER NOT NULL, checksum TEXT NOT NULL, requested_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE, FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS backup_policy_revisions (
 policy_id TEXT NOT NULL, revision INTEGER NOT NULL, enabled INTEGER NOT NULL, mode TEXT NOT NULL, consistency TEXT NOT NULL,
 compression TEXT NOT NULL, interval_seconds INTEGER NOT NULL, retention_count INTEGER NOT NULL, include_json TEXT NOT NULL,
 exclude_json TEXT NOT NULL, checksum TEXT NOT NULL, requested_by TEXT, created_at TEXT NOT NULL,
 PRIMARY KEY(policy_id,revision), FOREIGN KEY(policy_id) REFERENCES backup_policies(policy_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS backup_jobs (
 command_id TEXT PRIMARY KEY, backup_id TEXT, instance_id TEXT NOT NULL, agent_id TEXT NOT NULL, action TEXT NOT NULL,
 policy_revision INTEGER, status TEXT NOT NULL DEFAULT 'pending', reason TEXT, requested_by TEXT, size_bytes INTEGER,
 sha256 TEXT, artifact_path TEXT, started_at TEXT, completed_at TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE, FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_backup_jobs_backup_id ON backup_jobs(backup_id) WHERE backup_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_backup_jobs_agent_status ON backup_jobs(agent_id,status,created_at);
CREATE INDEX IF NOT EXISTS idx_backup_jobs_instance_completed ON backup_jobs(instance_id,completed_at);

-- source: 037_automation_broadcast.sql
CREATE TABLE IF NOT EXISTS automation_rules (
 rule_id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, trigger_json TEXT NOT NULL,
 conditions_json TEXT NOT NULL DEFAULT '[]', actions_json TEXT NOT NULL, cooldown_seconds INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL, checksum TEXT NOT NULL, requested_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_rule_revisions (
 rule_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL, trigger_json TEXT NOT NULL,
 conditions_json TEXT NOT NULL, actions_json TEXT NOT NULL, cooldown_seconds INTEGER NOT NULL, checksum TEXT NOT NULL,
 requested_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY(rule_id,revision),
 FOREIGN KEY(rule_id) REFERENCES automation_rules(rule_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS automation_runs (
 run_id TEXT PRIMARY KEY, rule_id TEXT, trigger_type TEXT NOT NULL, trigger_ref TEXT, status TEXT NOT NULL DEFAULT 'pending',
 context_json TEXT NOT NULL DEFAULT '{}', result_json TEXT NOT NULL DEFAULT '{}', requested_by TEXT,
 started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automation_runs_rule_created ON automation_runs(rule_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_automation_run_trigger ON automation_runs(rule_id,trigger_type,trigger_ref) WHERE trigger_ref IS NOT NULL;
CREATE TABLE IF NOT EXISTS automation_runtime_state (
 state_key TEXT PRIMARY KEY, state_value TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broadcasts (
 broadcast_id TEXT PRIMARY KEY, scope TEXT NOT NULL, target TEXT, message TEXT NOT NULL, priority TEXT NOT NULL,
 ttl_seconds INTEGER NOT NULL, require_ack INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending',
 requested_by TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broadcast_deliveries (
 delivery_id TEXT PRIMARY KEY, broadcast_id TEXT NOT NULL, agent_id TEXT NOT NULL, instance_id TEXT,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, delivered_at TEXT, acknowledged_at TEXT,
 last_error TEXT, updated_at TEXT NOT NULL, UNIQUE(broadcast_id,agent_id,instance_id),
 FOREIGN KEY(broadcast_id) REFERENCES broadcasts(broadcast_id) ON DELETE CASCADE,
 FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_broadcast_delivery_agent_status ON broadcast_deliveries(agent_id,status,updated_at);

-- source: 038_realtime_api_platform.sql
-- Capivara DSM - Migration 038 - SQLite
-- D2 Real-Time & API Platform.

CREATE TABLE IF NOT EXISTS api_tokens (
    token_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_prefix TEXT NOT NULL UNIQUE,
    secret_hash TEXT NOT NULL,
    scopes_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
    expires_at TEXT,
    last_used_at TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_status ON api_tokens(status, expires_at);

CREATE TABLE IF NOT EXISTS api_request_log (
    request_id TEXT PRIMARY KEY,
    token_id TEXT,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms REAL,
    remote_address TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(token_id) REFERENCES api_tokens(token_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_api_request_log_token_time ON api_request_log(token_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_request_log_time ON api_request_log(created_at DESC);

-- source: 039_multi_datacenter_federation.sql
-- Capivara DSM - Migration 039 - SQLite
-- E1 Multi-Datacenter Federation.

CREATE TABLE IF NOT EXISTS federation_members (
    controller_id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('global','regional','datacenter')),
    region_id TEXT,
    datacenter_id TEXT,
    public_endpoint TEXT,
    credential_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','degraded','offline','disabled')),
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(controller_id) REFERENCES controllers(id) ON DELETE CASCADE,
    FOREIGN KEY(region_id) REFERENCES regions(id) ON DELETE RESTRICT,
    FOREIGN KEY(datacenter_id) REFERENCES datacenters(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_federation_members_location ON federation_members(region_id, datacenter_id, status);

CREATE TABLE IF NOT EXISTS federation_inventory_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    FOREIGN KEY(controller_id) REFERENCES federation_members(controller_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_federation_inventory_member_time ON federation_inventory_snapshots(controller_id, generated_at DESC);

CREATE TABLE IF NOT EXISTS federation_policies (
    policy_id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global','region','datacenter','customer')),
    scope_id TEXT,
    mode TEXT NOT NULL DEFAULT 'local_first' CHECK (mode IN ('local_first','region_first','global')),
    cross_region_fallback INTEGER NOT NULL DEFAULT 0 CHECK (cross_region_fallback IN (0,1)),
    max_latency_ms INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_federation_policies_scope ON federation_policies(scope_type, scope_id);

CREATE TABLE IF NOT EXISTS federation_event_cursors (
    controller_id TEXT PRIMARY KEY,
    last_event_id TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(controller_id) REFERENCES federation_members(controller_id) ON DELETE CASCADE
);

-- source: 040_high_availability_disaster_recovery.sql
CREATE TABLE IF NOT EXISTS ha_clusters (
    cluster_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'manual',
    rpo_seconds INTEGER NOT NULL DEFAULT 300,
    rto_seconds INTEGER NOT NULL DEFAULT 900,
    quorum_size INTEGER NOT NULL DEFAULT 2,
    auto_failback INTEGER NOT NULL DEFAULT 0,
    fencing_epoch INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ha_cluster_members (
    cluster_id TEXT NOT NULL,
    controller_id TEXT NOT NULL,
    role TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'unknown',
    priority INTEGER NOT NULL DEFAULT 100,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(cluster_id, controller_id)
);
CREATE INDEX IF NOT EXISTS idx_ha_members_state ON ha_cluster_members(cluster_id, role, state, priority);
CREATE TABLE IF NOT EXISTS dr_recovery_points (
    recovery_point_id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    source_controller_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    location TEXT NOT NULL,
    checksum TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    validated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dr_points_cluster ON dr_recovery_points(cluster_id, created_at DESC);
CREATE TABLE IF NOT EXISTS ha_failover_operations (
    operation_id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    source_controller_id TEXT,
    target_controller_id TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT,
    requested_by TEXT,
    automatic INTEGER NOT NULL DEFAULT 0,
    fencing_epoch INTEGER NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ha_failover_cluster ON ha_failover_operations(cluster_id, created_at DESC);

-- source: 041_admin_destructive_deletion.sql
-- Capivara DSM - Migration 041 - SQLite
-- Add explicit transitional contract deletion state and Agent runtime remove action.

-- Rebuild the contract tables together so the parent CHECK can be expanded
-- without leaving a foreign key or trigger pointing at a dropped table.
CREATE TABLE service_contracts_v2 (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    game_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('pending','active','suspended','cancelled','expired','deleting')),
    instance_limit INTEGER NOT NULL DEFAULT 1 CHECK (instance_limit > 0),
    starts_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ends_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
);

CREATE TABLE instance_contracts_v2 (
    instance_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
    FOREIGN KEY (contract_id) REFERENCES service_contracts_v2(id) ON DELETE RESTRICT
);

INSERT INTO service_contracts_v2
SELECT id,customer_id,game_id,status,instance_limit,starts_at,ends_at,metadata_json,created_at,updated_at
FROM service_contracts;

INSERT INTO instance_contracts_v2(instance_id,contract_id,created_at)
SELECT instance_id,contract_id,created_at
FROM instance_contracts;

DROP TRIGGER IF EXISTS instance_contract_matches_insert;
DROP TRIGGER IF EXISTS instances_require_contract_before_active;
DROP TABLE instance_contracts;
DROP TABLE service_contracts;
ALTER TABLE service_contracts_v2 RENAME TO service_contracts;
ALTER TABLE instance_contracts_v2 RENAME TO instance_contracts;

CREATE TRIGGER instance_contract_matches_insert
BEFORE INSERT ON instance_contracts
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM instances i JOIN service_contracts c ON c.id=NEW.contract_id
        WHERE i.id=NEW.instance_id AND i.customer_id=c.customer_id AND i.game_id=c.game_id
          AND c.status='active' AND (c.ends_at IS NULL OR c.ends_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ) THEN RAISE(ABORT, 'instance_contract_mismatch') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM instance_contracts WHERE contract_id=NEW.contract_id
    ) >= (SELECT instance_limit FROM service_contracts WHERE id=NEW.contract_id)
    THEN RAISE(ABORT, 'contract_instance_limit_reached') END;
END;

CREATE TRIGGER instances_require_contract_before_active
BEFORE UPDATE OF status ON instances
WHEN NEW.status NOT IN ('pending','provisioning','deleting') AND NOT EXISTS (
    SELECT 1 FROM instance_contracts WHERE instance_id=NEW.id
)
BEGIN
    SELECT RAISE(ABORT, 'instance_requires_service_contract');
END;

CREATE INDEX idx_service_contracts_customer_status
    ON service_contracts(customer_id,status);
CREATE INDEX idx_instance_contracts_contract
    ON instance_contracts(contract_id);

-- Expand the Agent instance command allowlist with the destructive remove action.
CREATE TABLE agent_instance_commands_v3 (
    command_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('status','doctor','start','stop','restart','remove')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    requested_by TEXT,
    result_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);

INSERT INTO agent_instance_commands_v3
SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,
       created_at,delivered_at,completed_at,updated_at
FROM agent_instance_commands;

DROP TABLE agent_instance_commands;
ALTER TABLE agent_instance_commands_v3 RENAME TO agent_instance_commands;

CREATE INDEX idx_agent_instance_commands_agent_status
    ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance
    ON agent_instance_commands(instance_id,created_at);

