#!/usr/bin/env python3
"""Baseline schema extension for Agent public network installation settings."""
from __future__ import annotations


def ensure_agent_public_network_schema(sql: str, backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if "CREATE TABLE IF NOT EXISTS agent_public_network_preconfiguration" in sql:
        return sql
    if backend == "postgresql":
        ddl = """
CREATE TABLE IF NOT EXISTS agent_public_network_preconfiguration (
    installation_id TEXT PRIMARY KEY REFERENCES agent_pairing_tokens(id) ON DELETE CASCADE,
    public_hostname TEXT NULL,
    public_ipv4 TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
    elif backend in {"mysql", "mariadb"}:
        ddl = """
CREATE TABLE IF NOT EXISTS agent_public_network_preconfiguration (
    installation_id VARCHAR(128) PRIMARY KEY,
    public_hostname VARCHAR(253) NULL,
    public_ipv4 VARCHAR(45) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_agent_public_network_installation FOREIGN KEY (installation_id)
        REFERENCES agent_pairing_tokens(id) ON DELETE CASCADE
);
"""
    else:
        ddl = """
CREATE TABLE IF NOT EXISTS agent_public_network_preconfiguration (
    installation_id TEXT PRIMARY KEY REFERENCES agent_pairing_tokens(id) ON DELETE CASCADE,
    public_hostname TEXT NULL,
    public_ipv4 TEXT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
    return sql.rstrip() + "\n\n" + ddl.strip() + "\n"


__all__ = ["ensure_agent_public_network_schema"]
