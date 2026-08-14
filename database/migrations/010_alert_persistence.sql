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
