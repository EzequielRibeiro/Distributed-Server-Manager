#!/usr/bin/env python3
"""Canonical Dashboard activity-audit schema for Database Baseline v2."""
from __future__ import annotations


def dashboard_activity_ddl(backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if backend == "postgresql":
        return """CREATE TABLE dashboard_activity_log (
    event_id TEXT PRIMARY KEY,
    username TEXT,
    role TEXT,
    session_id TEXT,
    activity TEXT NOT NULL,
    category TEXT NOT NULL,
    result TEXT NOT NULL,
    method TEXT,
    path TEXT,
    status_code INTEGER,
    remote_address TEXT,
    user_agent TEXT,
    target_type TEXT,
    target_id TEXT,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_dashboard_activity_created ON dashboard_activity_log(created_at);
CREATE INDEX idx_dashboard_activity_user_created ON dashboard_activity_log(username,created_at);
CREATE INDEX idx_dashboard_activity_category_created ON dashboard_activity_log(category,created_at);
CREATE INDEX idx_dashboard_activity_session_created ON dashboard_activity_log(session_id,created_at);"""
    if backend == "sqlite":
        return """CREATE TABLE dashboard_activity_log (
    event_id TEXT PRIMARY KEY,
    username TEXT,
    role TEXT,
    session_id TEXT,
    activity TEXT NOT NULL,
    category TEXT NOT NULL,
    result TEXT NOT NULL,
    method TEXT,
    path TEXT,
    status_code INTEGER,
    remote_address TEXT,
    user_agent TEXT,
    target_type TEXT,
    target_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_dashboard_activity_created ON dashboard_activity_log(created_at);
CREATE INDEX idx_dashboard_activity_user_created ON dashboard_activity_log(username,created_at);
CREATE INDEX idx_dashboard_activity_category_created ON dashboard_activity_log(category,created_at);
CREATE INDEX idx_dashboard_activity_session_created ON dashboard_activity_log(session_id,created_at);"""
    return """CREATE TABLE dashboard_activity_log (
    event_id VARCHAR(64) NOT NULL PRIMARY KEY,
    username VARCHAR(191),
    role VARCHAR(32),
    session_id VARCHAR(128),
    activity VARCHAR(191) NOT NULL,
    category VARCHAR(64) NOT NULL,
    result VARCHAR(32) NOT NULL,
    method VARCHAR(16),
    path VARCHAR(1024),
    status_code INTEGER,
    remote_address VARCHAR(128),
    user_agent VARCHAR(1024),
    target_type VARCHAR(128),
    target_id VARCHAR(255),
    details_json JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_dashboard_activity_created (created_at),
    INDEX idx_dashboard_activity_user_created (username,created_at),
    INDEX idx_dashboard_activity_category_created (category,created_at),
    INDEX idx_dashboard_activity_session_created (session_id,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""


def ensure_dashboard_activity_schema(sql: str, backend: str) -> str:
    if "dashboard_activity_log" in sql.lower():
        return sql
    return sql.rstrip() + "\n\n" + dashboard_activity_ddl(backend) + "\n"


__all__ = ["dashboard_activity_ddl", "ensure_dashboard_activity_schema"]
