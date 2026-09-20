#!/usr/bin/env python3
"""Universal Controller-side operation diagnostics schema."""
from __future__ import annotations


def operation_diagnostics_ddl(backend: str) -> str:
    name = str(backend or "").strip().lower()
    if name == "postgresql":
        return """
CREATE TABLE IF NOT EXISTS operation_diagnostics (
    diagnostic_id TEXT PRIMARY KEY,
    correlation_id TEXT,
    operation TEXT NOT NULL,
    source TEXT,
    agent_id TEXT,
    instance_id TEXT,
    severity TEXT NOT NULL DEFAULT 'critical',
    current_step TEXT,
    error_code TEXT,
    exception_type TEXT,
    error TEXT,
    traceback TEXT,
    technical_detail TEXT,
    compensation_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_operation_diagnostics_correlation
    ON operation_diagnostics(correlation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_operation_diagnostics_instance
    ON operation_diagnostics(instance_id, created_at);
"""
    if name == "mysql":
        return """
CREATE TABLE IF NOT EXISTS operation_diagnostics (
    diagnostic_id VARCHAR(191) PRIMARY KEY,
    correlation_id VARCHAR(191),
    operation VARCHAR(128) NOT NULL,
    source VARCHAR(191),
    agent_id VARCHAR(191),
    instance_id VARCHAR(191),
    severity VARCHAR(32) NOT NULL DEFAULT 'critical',
    current_step VARCHAR(128),
    error_code VARCHAR(191),
    exception_type VARCHAR(191),
    error LONGTEXT,
    traceback LONGTEXT,
    technical_detail LONGTEXT,
    compensation_json LONGTEXT NOT NULL,
    payload_json LONGTEXT NOT NULL,
    occurred_at VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_operation_diagnostics_correlation
    ON operation_diagnostics(correlation_id, created_at);
CREATE INDEX idx_operation_diagnostics_instance
    ON operation_diagnostics(instance_id, created_at);
"""
    if name == "sqlite":
        return """
CREATE TABLE IF NOT EXISTS operation_diagnostics (
    diagnostic_id TEXT PRIMARY KEY,
    correlation_id TEXT,
    operation TEXT NOT NULL,
    source TEXT,
    agent_id TEXT,
    instance_id TEXT,
    severity TEXT NOT NULL DEFAULT 'critical',
    current_step TEXT,
    error_code TEXT,
    exception_type TEXT,
    error TEXT,
    traceback TEXT,
    technical_detail TEXT,
    compensation_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_operation_diagnostics_correlation
    ON operation_diagnostics(correlation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_operation_diagnostics_instance
    ON operation_diagnostics(instance_id, created_at);
"""
    raise ValueError(f"unsupported database backend: {backend}")


def ensure_operation_diagnostics_schema(sql: str, backend: str) -> str:
    if "create table operation_diagnostics" in sql.lower():
        return sql
    suffix = operation_diagnostics_ddl(backend)
    if str(backend).lower() == "mysql":
        suffix = suffix.replace("CREATE INDEX idx_operation_diagnostics_correlation", "CREATE INDEX idx_operation_diagnostics_correlation").replace("CREATE INDEX idx_operation_diagnostics_instance", "CREATE INDEX idx_operation_diagnostics_instance")
    alert_type = "VARCHAR(191)" if str(backend).lower() == "mysql" else "TEXT"
    return sql.rstrip() + f"\n\nALTER TABLE alerts ADD COLUMN diagnostic_id {alert_type};\n" + suffix + "\n"


__all__ = ["ensure_operation_diagnostics_schema", "operation_diagnostics_ddl"]
