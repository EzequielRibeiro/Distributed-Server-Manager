#!/usr/bin/env python3
"""Database-backed notification destinations and routing rules."""
from __future__ import annotations


def notification_destination_ddl(backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if backend == "postgresql":
        return """CREATE TABLE notification_destinations (
    destination_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    secret_file TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel,recipient)
);
CREATE TABLE notification_routes (
    route_id TEXT PRIMARY KEY,
    destination_id TEXT NOT NULL REFERENCES notification_destinations(destination_id) ON DELETE RESTRICT,
    event_type TEXT,
    minimum_severity TEXT NOT NULL DEFAULT 'warning' CHECK (minimum_severity IN ('info','warning','critical')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_notification_routes_match ON notification_routes(enabled,event_type,minimum_severity);"""
    if backend == "sqlite":
        return """CREATE TABLE notification_destinations (
    destination_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    secret_file TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel,recipient)
);
CREATE TABLE notification_routes (
    route_id TEXT PRIMARY KEY,
    destination_id TEXT NOT NULL REFERENCES notification_destinations(destination_id) ON DELETE RESTRICT,
    event_type TEXT,
    minimum_severity TEXT NOT NULL DEFAULT 'warning' CHECK (minimum_severity IN ('info','warning','critical')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_notification_routes_match ON notification_routes(enabled,event_type,minimum_severity);"""
    return """CREATE TABLE notification_destinations (
    destination_id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(191) NOT NULL UNIQUE,
    channel VARCHAR(64) NOT NULL,
    recipient VARCHAR(512) NOT NULL,
    secret_file TEXT,
    config_json TEXT NOT NULL,
    enabled TINYINT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_notification_destination_channel_recipient (channel,recipient),
    CONSTRAINT ck_notification_destinations_enabled CHECK (enabled IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE notification_routes (
    route_id VARCHAR(64) NOT NULL PRIMARY KEY,
    destination_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(191),
    minimum_severity VARCHAR(32) NOT NULL DEFAULT 'warning',
    enabled TINYINT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_notification_routes_match (enabled,event_type,minimum_severity),
    CONSTRAINT fk_notification_routes_destination FOREIGN KEY (destination_id) REFERENCES notification_destinations(destination_id) ON DELETE RESTRICT,
    CONSTRAINT ck_notification_routes_severity CHECK (minimum_severity IN ('info','warning','critical')),
    CONSTRAINT ck_notification_routes_enabled CHECK (enabled IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""


def ensure_notification_destination_schema(sql: str, backend: str) -> str:
    lowered = sql.lower()
    if "create table notification_destinations" in lowered and "create table notification_routes" in lowered:
        return sql
    return sql.rstrip() + "\n\n" + notification_destination_ddl(backend) + "\n"


__all__ = ["notification_destination_ddl", "ensure_notification_destination_schema"]
