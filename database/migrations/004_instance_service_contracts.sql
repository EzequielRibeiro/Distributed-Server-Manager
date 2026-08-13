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
