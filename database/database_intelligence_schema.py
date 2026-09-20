#!/usr/bin/env python3
"""Database Intelligence snapshot schema shared by all supported backends."""

from __future__ import annotations


def database_intelligence_ddl(backend: str) -> str:
    name = str(backend or "").strip().lower()
    if name == "postgresql":
        return """CREATE TABLE IF NOT EXISTS database_metrics_daily (
    snapshot_day DATE NOT NULL,
    table_name TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    backend TEXT NOT NULL,
    database_size_bytes BIGINT NOT NULL DEFAULT 0,
    row_count BIGINT NOT NULL DEFAULT 0,
    data_size_bytes BIGINT NOT NULL DEFAULT 0,
    index_size_bytes BIGINT NOT NULL DEFAULT 0,
    dead_rows BIGINT NOT NULL DEFAULT 0,
    insert_count BIGINT NOT NULL DEFAULT 0,
    update_count BIGINT NOT NULL DEFAULT 0,
    delete_count BIGINT NOT NULL DEFAULT 0,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_day, table_name)
);
CREATE INDEX IF NOT EXISTS idx_database_metrics_daily_captured
    ON database_metrics_daily(captured_at);
CREATE INDEX IF NOT EXISTS idx_database_metrics_daily_table_day
    ON database_metrics_daily(table_name, snapshot_day);"""
    if name == "sqlite":
        return """CREATE TABLE IF NOT EXISTS database_metrics_daily (
    snapshot_day TEXT NOT NULL,
    table_name TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    backend TEXT NOT NULL,
    database_size_bytes INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    data_size_bytes INTEGER NOT NULL DEFAULT 0,
    index_size_bytes INTEGER NOT NULL DEFAULT 0,
    dead_rows INTEGER NOT NULL DEFAULT 0,
    insert_count INTEGER NOT NULL DEFAULT 0,
    update_count INTEGER NOT NULL DEFAULT 0,
    delete_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (snapshot_day, table_name)
);
CREATE INDEX IF NOT EXISTS idx_database_metrics_daily_captured
    ON database_metrics_daily(captured_at);
CREATE INDEX IF NOT EXISTS idx_database_metrics_daily_table_day
    ON database_metrics_daily(table_name, snapshot_day);"""
    if name in {"mysql", "mariadb"}:
        return """CREATE TABLE IF NOT EXISTS database_metrics_daily (
    snapshot_day DATE NOT NULL,
    table_name VARCHAR(191) NOT NULL,
    captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    backend VARCHAR(32) NOT NULL,
    database_size_bytes BIGINT NOT NULL DEFAULT 0,
    row_count BIGINT NOT NULL DEFAULT 0,
    data_size_bytes BIGINT NOT NULL DEFAULT 0,
    index_size_bytes BIGINT NOT NULL DEFAULT 0,
    dead_rows BIGINT NOT NULL DEFAULT 0,
    insert_count BIGINT NOT NULL DEFAULT 0,
    update_count BIGINT NOT NULL DEFAULT 0,
    delete_count BIGINT NOT NULL DEFAULT 0,
    metadata_json JSON NOT NULL,
    PRIMARY KEY (snapshot_day, table_name),
    INDEX idx_database_metrics_daily_captured (captured_at),
    INDEX idx_database_metrics_daily_table_day (table_name, snapshot_day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""
    raise ValueError(f"unsupported database backend: {backend}")


__all__ = ["database_intelligence_ddl"]
