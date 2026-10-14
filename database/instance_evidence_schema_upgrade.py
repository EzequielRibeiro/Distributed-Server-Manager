"""Additive schema upgrade for instance evidence command parameters.

Must run under the backend's migration transaction before new queue code.
Does not alter consolidated schema files or their recorded checksums.
"""
from __future__ import annotations


def upgrade_evidence_parameters(connection, backend_name: str) -> bool:
    """Return True when the nullable column was added, False if already present.

    Caller owns transaction and must record the upgrade in migration bookkeeping.
    """
    name = str(backend_name).lower()
    cursor = connection.cursor()
    try:
        if name == 'sqlite':
            cursor.execute('PRAGMA table_info(agent_instance_commands)')
            columns = {row[1] for row in cursor.fetchall()}
            if not columns:
                raise RuntimeError('agent_instance_commands table missing')
            if 'parameters_json' in columns:
                return False
            cursor.execute('ALTER TABLE agent_instance_commands ADD COLUMN parameters_json TEXT')
            return True
        if name in ('postgresql', 'postgres'):
            cursor.execute('ALTER TABLE agent_instance_commands ADD COLUMN IF NOT EXISTS parameters_json TEXT')
            return True  # PostgreSQL IF NOT EXISTS is idempotent; existence is not reported.
        raise ValueError('unsupported backend')
    finally:
        cursor.close()
