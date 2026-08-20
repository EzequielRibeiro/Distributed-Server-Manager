ALTER TABLE agent_pairing_tokens ADD COLUMN platform TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN install_method TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN region_id TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN datacenter_id TEXT;
ALTER TABLE agent_pairing_tokens ADD COLUMN agent_id TEXT;

CREATE INDEX idx_agent_pairing_tokens_agent_id
    ON agent_pairing_tokens(agent_id);
CREATE INDEX idx_agent_pairing_tokens_datacenter_id
    ON agent_pairing_tokens(datacenter_id);
