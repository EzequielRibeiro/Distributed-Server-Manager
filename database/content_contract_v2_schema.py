#!/usr/bin/env python3
"""Baseline-v2 extension for Universal Content Contract v2."""
from __future__ import annotations
import re

_BACKENDS={"sqlite","postgresql","mysql","mariadb"}
_SECURITY_STATES="'unscanned','clean','suspicious','blocked','scan_failed'"


def ensure_content_contract_v2_schema(sql:str,backend:str)->str:
    backend=str(backend or "").strip().lower()
    if backend=="postgres":backend="postgresql"
    if backend not in _BACKENDS:raise ValueError(f"unsupported database backend: {backend}")
    if not re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?content_assignments\b",sql,re.IGNORECASE):
        raise ValueError(f"{backend} baseline has no content_assignments table")
    # Snapshots are historical consolidated inputs. The canonical Baseline v2
    # is the loader output, so extensions are appended here before checksum.
    if re.search(r"ALTER\s+TABLE\s+content_assignments\s+ADD\s+COLUMN\s+activation_state\b",sql,re.IGNORECASE):return sql
    integer="BIGINT" if backend=="postgresql" else "INTEGER"
    if backend in {"mysql","mariadb"}:
        state_type="VARCHAR(16)";security_type="VARCHAR(32)";json_type="JSON NOT NULL"
        provenance=f"provenance_json {json_type}"
        metadata=f"metadata_json {json_type}"
    else:
        state_type="TEXT";security_type="TEXT";provenance="provenance_json TEXT NOT NULL DEFAULT '{}'";metadata="metadata_json TEXT NOT NULL DEFAULT '{}'"
    statements=[
        f"ALTER TABLE content_assignments ADD COLUMN activation_state {state_type} NOT NULL DEFAULT 'enabled' CHECK (activation_state IN ('enabled','disabled'));",
        f"ALTER TABLE content_assignments ADD COLUMN activation_order {integer} NOT NULL DEFAULT 0 CHECK (activation_order BETWEEN 0 AND 1000000);",
        f"ALTER TABLE content_assignments ADD COLUMN {provenance};",
        f"ALTER TABLE content_assignments ADD COLUMN {metadata};",
        f"ALTER TABLE content_assignments ADD COLUMN security_state {security_type} NOT NULL DEFAULT 'unscanned' CHECK (security_state IN ({_SECURITY_STATES}));",
        f"ALTER TABLE content_assignment_revisions ADD COLUMN activation_state {state_type} NOT NULL DEFAULT 'enabled' CHECK (activation_state IN ('enabled','disabled'));",
        f"ALTER TABLE content_assignment_revisions ADD COLUMN activation_order {integer} NOT NULL DEFAULT 0 CHECK (activation_order BETWEEN 0 AND 1000000);",
        f"ALTER TABLE content_assignment_revisions ADD COLUMN {provenance};",
        f"ALTER TABLE content_assignment_revisions ADD COLUMN {metadata};",
        f"ALTER TABLE content_assignment_revisions ADD COLUMN security_state {security_type} NOT NULL DEFAULT 'unscanned' CHECK (security_state IN ({_SECURITY_STATES}));",
        f"ALTER TABLE agent_content_state ADD COLUMN security_state {security_type} NOT NULL DEFAULT 'unscanned' CHECK (security_state IN ({_SECURITY_STATES}));",
    ]
    return sql.rstrip()+"\n\n-- Universal Content Contract v2\n"+"\n".join(statements)+"\n"


__all__=["ensure_content_contract_v2_schema"]
