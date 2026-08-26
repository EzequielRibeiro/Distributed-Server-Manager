#!/usr/bin/env python3
"""Canonical semantic operator-audit schema for Database Baseline v2."""
from __future__ import annotations


def activity_audit_ddl(backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if backend == "postgresql":
        return """CREATE TABLE activity_audit (
    activity_id TEXT PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id TEXT,
    actor_name TEXT,
    actor_role TEXT,
    action TEXT NOT NULL,
    category TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    target_name TEXT,
    result TEXT NOT NULL,
    summary TEXT NOT NULL,
    changes_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id TEXT,
    remote_address TEXT,
    user_agent TEXT
);
CREATE INDEX idx_activity_audit_time ON activity_audit(occurred_at);
CREATE INDEX idx_activity_audit_actor_time ON activity_audit(actor_id,occurred_at);
CREATE INDEX idx_activity_audit_category_time ON activity_audit(category,occurred_at);
CREATE INDEX idx_activity_audit_target_time ON activity_audit(target_type,target_id,occurred_at);
CREATE INDEX idx_activity_audit_correlation ON activity_audit(correlation_id);"""
    if backend == "sqlite":
        return """CREATE TABLE activity_audit (
    activity_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id TEXT,
    actor_name TEXT,
    actor_role TEXT,
    action TEXT NOT NULL,
    category TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    target_name TEXT,
    result TEXT NOT NULL,
    summary TEXT NOT NULL,
    changes_json TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT,
    remote_address TEXT,
    user_agent TEXT
);
CREATE INDEX idx_activity_audit_time ON activity_audit(occurred_at);
CREATE INDEX idx_activity_audit_actor_time ON activity_audit(actor_id,occurred_at);
CREATE INDEX idx_activity_audit_category_time ON activity_audit(category,occurred_at);
CREATE INDEX idx_activity_audit_target_time ON activity_audit(target_type,target_id,occurred_at);
CREATE INDEX idx_activity_audit_correlation ON activity_audit(correlation_id);"""
    return """CREATE TABLE activity_audit (
    activity_id VARCHAR(64) NOT NULL PRIMARY KEY,
    occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id VARCHAR(191),
    actor_name VARCHAR(191),
    actor_role VARCHAR(32),
    action VARCHAR(191) NOT NULL,
    category VARCHAR(64) NOT NULL,
    target_type VARCHAR(128),
    target_id VARCHAR(255),
    target_name VARCHAR(255),
    result VARCHAR(32) NOT NULL,
    summary TEXT NOT NULL,
    changes_json JSON NOT NULL,
    correlation_id VARCHAR(191),
    remote_address VARCHAR(128),
    user_agent VARCHAR(1024),
    INDEX idx_activity_audit_time (occurred_at),
    INDEX idx_activity_audit_actor_time (actor_id,occurred_at),
    INDEX idx_activity_audit_category_time (category,occurred_at),
    INDEX idx_activity_audit_target_time (target_type,target_id,occurred_at),
    INDEX idx_activity_audit_correlation (correlation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""


def ensure_activity_audit_schema(sql: str, backend: str) -> str:
    if "create table activity_audit" in sql.lower():
        return sql
    return sql.rstrip() + "\n\n" + activity_audit_ddl(backend) + "\n"


__all__ = ["activity_audit_ddl", "ensure_activity_audit_schema"]
