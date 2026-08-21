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
