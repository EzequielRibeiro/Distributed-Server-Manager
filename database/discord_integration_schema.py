#!/usr/bin/env python3
"""Generic customer Discord integration schema for Database Baseline v2."""
from __future__ import annotations


def discord_integration_ddl(backend: str) -> str:
    backend = str(backend or "").strip().lower()
    timestamp = "TIMESTAMPTZ" if backend == "postgresql" else "TEXT" if backend == "sqlite" else "TIMESTAMP"
    id_type = "TEXT" if backend in {"postgresql", "sqlite"} else "VARCHAR(191)"
    bool_type = "BOOLEAN" if backend == "postgresql" else "INTEGER" if backend == "sqlite" else "TINYINT(1)"
    return f"""CREATE TABLE customer_discord_connections (
    id {id_type} PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    guild_id {id_type} NOT NULL,
    guild_name {id_type} NOT NULL,
    guild_icon TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    is_default {bool_type} NOT NULL DEFAULT 0,
    created_by {id_type},
    created_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id,guild_id),
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE INDEX idx_customer_discord_connections_customer ON customer_discord_connections(customer_id,status);

CREATE TABLE customer_discord_instance_bindings (
    customer_id INTEGER NOT NULL,
    instance_id {id_type} NOT NULL,
    mode VARCHAR(16) NOT NULL DEFAULT 'inherit',
    connection_id {id_type},
    channel_id {id_type},
    channel_name {id_type},
    enabled {bool_type} NOT NULL DEFAULT 1,
    updated_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(customer_id,instance_id),
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY(connection_id) REFERENCES customer_discord_connections(id) ON DELETE SET NULL,
    CHECK (mode IN ('inherit','connection','disabled'))
);
CREATE INDEX idx_customer_discord_bindings_connection ON customer_discord_instance_bindings(connection_id);

CREATE TABLE customer_discord_preferences (
    customer_id INTEGER NOT NULL,
    instance_id {id_type} NOT NULL DEFAULT '*',
    preference_type VARCHAR(16) NOT NULL,
    preference_key {id_type} NOT NULL,
    enabled {bool_type} NOT NULL DEFAULT 1,
    channel_id {id_type},
    discord_role_id {id_type},
    require_confirmation {bool_type} NOT NULL DEFAULT 0,
    updated_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(customer_id,instance_id,preference_type,preference_key),
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    CHECK (preference_type IN ('event','command'))
);

CREATE TABLE customer_discord_oauth_states (
    state {id_type} PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    username {id_type} NOT NULL,
    expires_at {timestamp} NOT NULL,
    created_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);"""


def ensure_discord_integration_schema(sql: str, backend: str) -> str:
    if "create table customer_discord_connections" in sql.lower():
        return sql
    return sql.rstrip() + "\n\n" + discord_integration_ddl(backend) + "\n"


__all__ = ["discord_integration_ddl", "ensure_discord_integration_schema"]
