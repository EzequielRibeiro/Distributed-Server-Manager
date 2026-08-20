ALTER TABLE agent_pairing_tokens ADD COLUMN platform VARCHAR(32) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN install_method VARCHAR(32) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN region_id VARCHAR(191) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN datacenter_id VARCHAR(191) NULL;
ALTER TABLE agent_pairing_tokens ADD COLUMN agent_id VARCHAR(191) NULL;

CREATE INDEX idx_agent_pairing_tokens_agent_id
    ON agent_pairing_tokens(agent_id);
CREATE INDEX idx_agent_pairing_tokens_datacenter_id
    ON agent_pairing_tokens(datacenter_id);
