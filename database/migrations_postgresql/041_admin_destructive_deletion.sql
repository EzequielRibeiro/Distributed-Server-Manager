-- Capivara DSM - Migration 041 - PostgreSQL
-- Add explicit transitional contract deletion state and Agent runtime remove action.

DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    SELECT c.conname
      INTO constraint_name
      FROM pg_constraint c
      JOIN pg_class t ON t.oid = c.conrelid
     WHERE t.relname = 'service_contracts'
       AND c.contype = 'c'
       AND pg_get_constraintdef(c.oid) LIKE '%status%pending%active%suspended%cancelled%expired%'
     LIMIT 1;

    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE service_contracts DROP CONSTRAINT %I', constraint_name);
    END IF;
END
$$;

ALTER TABLE service_contracts
    ADD CONSTRAINT service_contracts_status_check
    CHECK (status IN ('pending','active','suspended','cancelled','expired','deleting'));

CREATE TABLE agent_instance_commands_v3 (
    command_id VARCHAR(191) PRIMARY KEY,
    agent_id VARCHAR(191) NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    instance_id VARCHAR(191) NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    action VARCHAR(16) NOT NULL CHECK (action IN ('status','doctor','start','stop','restart','remove')),
    status VARCHAR(16) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','completed','failed')),
    requested_by VARCHAR(191),
    result_json TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO agent_instance_commands_v3
(command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at)
SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error,created_at,delivered_at,completed_at,updated_at
FROM agent_instance_commands;

DROP TABLE agent_instance_commands;
ALTER TABLE agent_instance_commands_v3 RENAME TO agent_instance_commands;

CREATE INDEX idx_agent_instance_commands_agent_status
    ON agent_instance_commands(agent_id,status,created_at);
CREATE INDEX idx_agent_instance_commands_instance
    ON agent_instance_commands(instance_id,created_at);
