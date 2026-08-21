-- Capivara DSM - Migration 038 - MySQL/MariaDB
CREATE TABLE IF NOT EXISTS api_tokens (
 token_id VARCHAR(191) PRIMARY KEY, name VARCHAR(191) NOT NULL, token_prefix VARCHAR(191) NOT NULL UNIQUE, secret_hash VARCHAR(64) NOT NULL,
 scopes_json LONGTEXT NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active', expires_at VARCHAR(40), last_used_at VARCHAR(40),
 created_by VARCHAR(191), created_at VARCHAR(40) NOT NULL, revoked_at VARCHAR(40), INDEX idx_api_tokens_status(status,expires_at)
);
CREATE TABLE IF NOT EXISTS api_request_log (
 request_id VARCHAR(191) PRIMARY KEY, token_id VARCHAR(191), method VARCHAR(16) NOT NULL, path VARCHAR(512) NOT NULL,
 status_code INT NOT NULL, latency_ms DOUBLE, remote_address VARCHAR(191), created_at VARCHAR(40) NOT NULL,
 INDEX idx_api_request_log_token_time(token_id,created_at), INDEX idx_api_request_log_time(created_at),
 FOREIGN KEY(token_id) REFERENCES api_tokens(token_id) ON DELETE SET NULL
);
