-- Capivara DSM - Migration 038 - PostgreSQL
CREATE TABLE IF NOT EXISTS api_tokens (
 token_id TEXT PRIMARY KEY, name TEXT NOT NULL, token_prefix TEXT NOT NULL UNIQUE, secret_hash TEXT NOT NULL,
 scopes_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active', expires_at TEXT, last_used_at TEXT,
 created_by TEXT, created_at TEXT NOT NULL, revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_status ON api_tokens(status,expires_at);
CREATE TABLE IF NOT EXISTS api_request_log (
 request_id TEXT PRIMARY KEY, token_id TEXT, method TEXT NOT NULL, path TEXT NOT NULL, status_code INTEGER NOT NULL,
 latency_ms DOUBLE PRECISION, remote_address TEXT, created_at TEXT NOT NULL,
 FOREIGN KEY(token_id) REFERENCES api_tokens(token_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_api_request_log_token_time ON api_request_log(token_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_request_log_time ON api_request_log(created_at DESC);
