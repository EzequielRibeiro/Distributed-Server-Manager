#!/usr/bin/env python3
"""Durable notification outbox schema for Database Baseline v2."""
from __future__ import annotations


def notification_outbox_ddl(backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if backend == "postgresql":
        return """CREATE TABLE notification_outbox (
    notification_id TEXT PRIMARY KEY,
    event_id TEXT,
    alert_id TEXT,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','delivered','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_notification_outbox_pending ON notification_outbox(status,next_attempt_at,created_at);
CREATE INDEX idx_notification_outbox_event ON notification_outbox(event_id,created_at);
CREATE INDEX idx_notification_outbox_alert ON notification_outbox(alert_id,created_at);"""
    if backend == "sqlite":
        return """CREATE TABLE notification_outbox (
    notification_id TEXT PRIMARY KEY,
    event_id TEXT,
    alert_id TEXT,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','delivered','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    delivered_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_notification_outbox_pending ON notification_outbox(status,next_attempt_at,created_at);
CREATE INDEX idx_notification_outbox_event ON notification_outbox(event_id,created_at);
CREATE INDEX idx_notification_outbox_alert ON notification_outbox(alert_id,created_at);"""
    return """CREATE TABLE notification_outbox (
    notification_id VARCHAR(64) NOT NULL PRIMARY KEY,
    event_id VARCHAR(64),
    alert_id VARCHAR(191),
    channel VARCHAR(64) NOT NULL,
    recipient VARCHAR(512) NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP NULL,
    delivered_at TIMESTAMP NULL,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_notification_outbox_pending (status,next_attempt_at,created_at),
    INDEX idx_notification_outbox_event (event_id,created_at),
    INDEX idx_notification_outbox_alert (alert_id,created_at),
    CONSTRAINT ck_notification_outbox_status CHECK (status IN ('pending','processing','delivered','failed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""


def ensure_notification_outbox_schema(sql: str, backend: str) -> str:
    if "create table notification_outbox" in sql.lower():
        return sql
    return sql.rstrip() + "\n\n" + notification_outbox_ddl(backend) + "\n"


__all__ = ["notification_outbox_ddl", "ensure_notification_outbox_schema"]
