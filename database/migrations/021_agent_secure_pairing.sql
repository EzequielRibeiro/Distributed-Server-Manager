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
