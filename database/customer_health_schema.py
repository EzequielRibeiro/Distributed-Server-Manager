#!/usr/bin/env python3
"""Customer functional health incident schema for Database Baseline v2."""
from __future__ import annotations


def customer_health_ddl(backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if backend == "postgresql":
        return """CREATE TABLE customer_health_incidents (
    incident_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    customer_id TEXT NOT NULL,
    controller_id TEXT NOT NULL,
    category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('OPEN','ACKNOWLEDGED','RESOLVED')),
    safe_code TEXT,
    message TEXT NOT NULL,
    action TEXT,
    instance_id TEXT,
    contract_id TEXT,
    correlation_id TEXT,
    root_type TEXT,
    root_id TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ
);
CREATE INDEX idx_customer_health_active ON customer_health_incidents(state,severity,updated_at);
CREATE INDEX idx_customer_health_customer ON customer_health_incidents(customer_id,state,updated_at);
CREATE INDEX idx_customer_health_controller ON customer_health_incidents(controller_id,state,updated_at);
CREATE INDEX idx_customer_health_correlation ON customer_health_incidents(correlation_id);
CREATE TABLE customer_health_events (
    event_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    safe_code TEXT,
    message TEXT NOT NULL,
    correlation_id TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (incident_id) REFERENCES customer_health_incidents(incident_id) ON DELETE CASCADE
);
CREATE INDEX idx_customer_health_events_incident ON customer_health_events(incident_id,occurred_at);"""
    if backend == "sqlite":
        return """CREATE TABLE customer_health_incidents (
    incident_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    customer_id TEXT NOT NULL,
    controller_id TEXT NOT NULL,
    category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('OPEN','ACKNOWLEDGED','RESOLVED')),
    safe_code TEXT,
    message TEXT NOT NULL,
    action TEXT,
    instance_id TEXT,
    contract_id TEXT,
    correlation_id TEXT,
    root_type TEXT,
    root_id TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TEXT,
    resolved_at TEXT
);
CREATE INDEX idx_customer_health_active ON customer_health_incidents(state,severity,updated_at);
CREATE INDEX idx_customer_health_customer ON customer_health_incidents(customer_id,state,updated_at);
CREATE INDEX idx_customer_health_controller ON customer_health_incidents(controller_id,state,updated_at);
CREATE INDEX idx_customer_health_correlation ON customer_health_incidents(correlation_id);
CREATE TABLE customer_health_events (
    event_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    safe_code TEXT,
    message TEXT NOT NULL,
    correlation_id TEXT,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (incident_id) REFERENCES customer_health_incidents(incident_id) ON DELETE CASCADE
);
CREATE INDEX idx_customer_health_events_incident ON customer_health_events(incident_id,occurred_at);"""
    return """CREATE TABLE customer_health_incidents (
    incident_id VARCHAR(64) NOT NULL PRIMARY KEY,
    dedupe_key VARCHAR(255) NOT NULL UNIQUE,
    customer_id VARCHAR(191) NOT NULL,
    controller_id VARCHAR(191) NOT NULL,
    category VARCHAR(64) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    state VARCHAR(16) NOT NULL,
    safe_code VARCHAR(128),
    message TEXT NOT NULL,
    action VARCHAR(191),
    instance_id VARCHAR(191),
    contract_id VARCHAR(191),
    correlation_id VARCHAR(191),
    root_type VARCHAR(64),
    root_id VARCHAR(191),
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMP NULL,
    resolved_at TIMESTAMP NULL,
    INDEX idx_customer_health_active (state,severity,updated_at),
    INDEX idx_customer_health_customer (customer_id,state,updated_at),
    INDEX idx_customer_health_controller (controller_id,state,updated_at),
    INDEX idx_customer_health_correlation (correlation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE customer_health_events (
    event_id VARCHAR(64) NOT NULL PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    old_state VARCHAR(16),
    new_state VARCHAR(16) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    safe_code VARCHAR(128),
    message TEXT NOT NULL,
    correlation_id VARCHAR(191),
    occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_customer_health_events_incident FOREIGN KEY (incident_id) REFERENCES customer_health_incidents(incident_id) ON DELETE CASCADE,
    INDEX idx_customer_health_events_incident (incident_id,occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""


def ensure_customer_health_schema(sql: str, backend: str) -> str:
    if "create table customer_health_incidents" in sql.lower():
        return sql
    return sql.rstrip() + "\n\n" + customer_health_ddl(backend) + "\n"


__all__ = ["customer_health_ddl", "ensure_customer_health_schema"]
