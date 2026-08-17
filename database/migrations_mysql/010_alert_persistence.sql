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
