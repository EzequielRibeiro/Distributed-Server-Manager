#!/usr/bin/env python3
"""Composed Universal Content bundle schema for Database Baseline v2."""
from __future__ import annotations

def content_bundle_ddl(backend:str)->str:
 b=str(backend or "").strip().lower()
 if b=="postgresql":ident="TEXT";big="BIGINT";blob="TEXT";ts="TIMESTAMPTZ"
 elif b in {"mysql","mariadb"}:ident="VARCHAR(191)";big="BIGINT";blob="LONGTEXT";ts="VARCHAR(40)"
 else:ident="TEXT";big="INTEGER";blob="TEXT";ts="TEXT"
 engine=" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if b in {"mysql","mariadb"} else "";index_if="" if b in {"mysql","mariadb"} else " IF NOT EXISTS"
 return f"""CREATE TABLE IF NOT EXISTS content_bundles (
 bundle_id {ident} PRIMARY KEY, instance_id {ident} NOT NULL, parent_assignment_id {ident} NOT NULL, parent_content_id {ident} NOT NULL,
 provider VARCHAR(64) NOT NULL, provider_project_id {ident} NOT NULL, provider_version_id {ident} NOT NULL,
 minecraft_version VARCHAR(64) NOT NULL, loader_id VARCHAR(32) NOT NULL, loader_version {ident}, manifest_kind VARCHAR(32) NOT NULL,
 manifest_sha256 VARCHAR(64) NOT NULL, override_roots_json {blob} NOT NULL, revision {big} NOT NULL, checksum VARCHAR(64) NOT NULL,
 requested_by {ident}, created_at {ts} NOT NULL, updated_at {ts} NOT NULL, UNIQUE(instance_id,parent_content_id)
){engine};
CREATE TABLE IF NOT EXISTS content_bundle_revisions (
 bundle_id {ident} NOT NULL, revision {big} NOT NULL, parent_assignment_id {ident} NOT NULL,
 provider VARCHAR(64) NOT NULL, provider_project_id {ident} NOT NULL, provider_version_id {ident} NOT NULL,
 minecraft_version VARCHAR(64) NOT NULL, loader_id VARCHAR(32) NOT NULL, loader_version {ident}, manifest_kind VARCHAR(32) NOT NULL,
 manifest_sha256 VARCHAR(64) NOT NULL, manifest_json {blob} NOT NULL, override_roots_json {blob} NOT NULL, checksum VARCHAR(64) NOT NULL,
 requested_by {ident}, created_at {ts} NOT NULL, PRIMARY KEY(bundle_id,revision)
){engine};
CREATE INDEX{index_if} idx_content_bundles_instance ON content_bundles(instance_id,parent_content_id);"""

def ensure_content_bundle_schema(sql:str,backend:str)->str:
 if "create table if not exists content_bundles" in sql.lower():return sql
 return sql.rstrip()+"\n\n-- Universal Content Bundle Contract\n"+content_bundle_ddl(backend)+"\n"

__all__=["content_bundle_ddl","ensure_content_bundle_schema"]
