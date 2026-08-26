#!/usr/bin/env python3
"""Canonical migration-free database schema baseline contract."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
from activity_audit_schema import ensure_activity_audit_schema
from artifact_transfer_schema import ensure_artifact_transfer_schema
from baseline_backend_compat import finalize_baseline_sql
from baseline_v2_compiler import compile_baseline_v2
from instance_workspace_schema import ensure_instance_workspace_schema
from instance_workspace_extended_schema import ensure_instance_workspace_extended_schema
from notification_outbox_schema import ensure_notification_outbox_schema
DATABASE_DIR=Path(__file__).resolve().parent;SCHEMA_DIR=DATABASE_DIR/"schemas";BASELINE_NAME="capivara-baseline-v2"
_SCHEMA_FILES={"sqlite":"sqlite.sql","postgresql":"postgresql.sql","mysql":"mysql.sql","mariadb":"mariadb.sql"}
@dataclass(frozen=True)
class SchemaBaseline:
 backend:str;name:str;path:Path;sql:str;checksum:str
def normalize_backend_name(value):
 backend=str(value or "").strip().lower()
 if backend=="postgres":backend="postgresql"
 if backend not in _SCHEMA_FILES:raise ValueError(f"unsupported database backend: {value}")
 return backend
def schema_path(backend):return SCHEMA_DIR/_SCHEMA_FILES[normalize_backend_name(backend)]
def load_schema_baseline(backend):
 normalized=normalize_backend_name(backend);path=schema_path(normalized)
 if not path.is_file():raise FileNotFoundError(f"database schema baseline not found: {path}")
 source_sql=path.read_text(encoding="utf-8")
 if not source_sql.strip():raise ValueError(f"database schema baseline is empty: {path}")
 sql=compile_baseline_v2(source_sql,normalized);sql=finalize_baseline_sql(sql,normalized);sql=ensure_activity_audit_schema(sql,normalized);sql=ensure_notification_outbox_schema(sql,normalized);sql=ensure_instance_workspace_schema(sql,normalized);sql=ensure_instance_workspace_extended_schema(sql,normalized);sql=ensure_artifact_transfer_schema(sql,normalized)
 return SchemaBaseline(normalized,BASELINE_NAME,path,sql,hashlib.sha256(sql.encode()).hexdigest())
def baseline_marker_sql(backend):
 normalized=normalize_backend_name(backend)
 if normalized=="postgresql":return "CREATE TABLE IF NOT EXISTS schema_baseline (singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),name TEXT NOT NULL,checksum TEXT NOT NULL,installed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
 if normalized in {"mysql","mariadb"}:return "CREATE TABLE IF NOT EXISTS schema_baseline (singleton TINYINT NOT NULL PRIMARY KEY DEFAULT 1,name VARCHAR(128) NOT NULL,checksum VARCHAR(64) NOT NULL,installed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT ck_schema_baseline_singleton CHECK (singleton = 1))"
 return "CREATE TABLE IF NOT EXISTS schema_baseline (singleton INTEGER NOT NULL PRIMARY KEY DEFAULT 1 CHECK (singleton = 1),name TEXT NOT NULL,checksum TEXT NOT NULL,installed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
__all__=["BASELINE_NAME","DATABASE_DIR","SCHEMA_DIR","SchemaBaseline","baseline_marker_sql","load_schema_baseline","normalize_backend_name","schema_path"]
