"""Tracked additive migration for existing Capivara schemas (not auto-run).

Version 41 consolidated checksum remains untouched. Call under a controlled
upgrade transaction before enabling the evidence command queue.
"""
from __future__ import annotations
import hashlib

VERSION = 42
NAME = 'instance_evidence_parameters'
SQL = 'ALTER TABLE agent_instance_commands ADD COLUMN parameters_json TEXT'
CHECKSUM = hashlib.sha256(SQL.encode('utf-8')).hexdigest()


def migrate_sqlite(connection):
    """Apply and track v42 atomically; never rewrite v41's checksum."""
    current = connection.execute('SELECT name, checksum FROM schema_migrations WHERE version=?', (VERSION,)).fetchone()
    if current is not None:
        if tuple(current) != (NAME, CHECKSUM):
            raise RuntimeError('evidence migration checksum mismatch')
        columns = {row[1] for row in connection.execute('PRAGMA table_info(agent_instance_commands)')}
        if 'parameters_json' not in columns:
            raise RuntimeError('evidence migration recorded without column')
        return False
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
        own_transaction = True
    else:
        own_transaction = False
    try:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(agent_instance_commands)')}
        if not columns:
            raise RuntimeError('instance command table missing')
        if 'parameters_json' not in columns:
            connection.execute(SQL)
        connection.execute('INSERT INTO schema_migrations(version,name,checksum) VALUES (?,?,?)', (VERSION, NAME, CHECKSUM))
        if own_transaction:
            connection.commit()
    except Exception:
        if own_transaction:
            connection.rollback()
        raise
    return True
