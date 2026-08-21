-- Capivara DSM - Migration 037 - SQLite
-- Add explicit transitional contract deletion state and Agent runtime remove action.

-- Rebuild the contract tables together so the parent CHECK can be expanded
-- without leaving a foreign key pointing at a dropped table.
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
