#!/usr/bin/env python3
"""Baseline extension for outbound-only Agent artifact transfers."""
from __future__ import annotations

def ensure_artifact_transfer_schema(sql:str,backend:str)->str:
 backend=str(backend or "").lower()
 if "CREATE TABLE IF NOT EXISTS artifact_transfers" in sql:return sql
 if backend in {"mysql","mariadb"}:
  ident="VARCHAR(191)";medium="VARCHAR(1024)";bigint="BIGINT";timestamp="TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP";timestamp_null="TIMESTAMP NULL";index="CREATE INDEX"
 elif backend=="postgresql":
  ident="TEXT";medium="TEXT";bigint="BIGINT";timestamp="TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP";timestamp_null="TIMESTAMPTZ";index="CREATE INDEX IF NOT EXISTS"
 else:
  ident="TEXT";medium="TEXT";bigint="INTEGER";timestamp="TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP";timestamp_null="TEXT";index="CREATE INDEX IF NOT EXISTS"
 ddl=f"""

-- Distributed Artifact Transfer Plane -------------------------------------
CREATE TABLE IF NOT EXISTS artifact_transfers (
 transfer_id {ident} PRIMARY KEY,
 agent_id {ident} NOT NULL,
 instance_id {ident},
 customer_id {bigint},
 direction {ident} NOT NULL,
 purpose {ident} NOT NULL,
 source_ref {medium},
 destination_ref {medium},
 filename {medium} NOT NULL,
 status {ident} NOT NULL DEFAULT 'queued',
 size_bytes {bigint},
 transferred_bytes {bigint} NOT NULL DEFAULT 0,
 sha256 {ident},
 controller_path {medium},
 requested_by {ident},
 last_error {medium},
 created_at {timestamp},
 delivered_at {timestamp_null},
 completed_at {timestamp_null},
 expires_at {timestamp_null},
 updated_at {timestamp},
 FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
 FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE SET NULL,
 FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
{index} idx_artifact_transfer_agent_status ON artifact_transfers(agent_id,status,created_at);
{index} idx_artifact_transfer_customer_status ON artifact_transfers(customer_id,status,created_at);
{index} idx_artifact_transfer_expiry ON artifact_transfers(expires_at,status);
"""
 return sql.rstrip()+ddl+"\n"

__all__=["ensure_artifact_transfer_schema"]
