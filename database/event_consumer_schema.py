#!/usr/bin/env python3
"""Database cursors for durable Universal Event consumers."""
from __future__ import annotations


def event_consumer_ddl(backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if backend == "postgresql":
        return """CREATE TABLE event_consumer_cursors (
    consumer_id TEXT PRIMARY KEY,
    received_at TIMESTAMPTZ,
    event_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);"""
    if backend == "sqlite":
        return """CREATE TABLE event_consumer_cursors (
    consumer_id TEXT PRIMARY KEY,
    received_at TEXT,
    event_id TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);"""
    return """CREATE TABLE event_consumer_cursors (
    consumer_id VARCHAR(191) NOT NULL PRIMARY KEY,
    received_at TIMESTAMP NULL,
    event_id VARCHAR(64),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""


def ensure_event_consumer_schema(sql: str, backend: str) -> str:
    if "create table event_consumer_cursors" in sql.lower():
        return sql
    return sql.rstrip() + "\n\n" + event_consumer_ddl(backend) + "\n"


__all__ = ["event_consumer_ddl", "ensure_event_consumer_schema"]
