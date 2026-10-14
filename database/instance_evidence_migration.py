"""Tracked additive migration for existing Capivara schemas (not auto-run).

Version 41 consolidated checksum remains untouched; source migration 042 is reserved. Call under a controlled
upgrade transaction before enabling the evidence command queue.
"""
from __future__ import annotations
import hashlib

VERSION = 43
NAME = 'instance_evidence_parameters'
SQL = 'ALTER TABLE agent_instance_commands ADD COLUMN parameters_json TEXT'
CHECKSUM = hashlib.sha256(SQL.encode('utf-8')).hexdigest()


def migrate_sqlite(connection):
    """Apply and track v43 in one SQLite write transaction.

    The caller must not hold an existing transaction; BEGIN IMMEDIATE serializes
    competing migrators before either reads the version row.
    """
    if connection.in_transaction:
        raise RuntimeError('sqlite migration requires an independent transaction')
    connection.execute('BEGIN IMMEDIATE')
    try:
        current = connection.execute('SELECT name, checksum FROM schema_migrations WHERE version=?', (VERSION,)).fetchone()
        columns = {row[1] for row in connection.execute('PRAGMA table_info(agent_instance_commands)')}
        if current is not None:
            if tuple(current) != (NAME, CHECKSUM):
                raise RuntimeError('evidence migration checksum mismatch')
            if 'parameters_json' not in columns:
                raise RuntimeError('evidence migration recorded without column')
            connection.commit()
            return False
        if not columns:
            raise RuntimeError('instance command table missing')
        if 'parameters_json' not in columns:
            connection.execute(SQL)
        connection.execute('INSERT INTO schema_migrations(version,name,checksum) VALUES (?,?,?)', (VERSION, NAME, CHECKSUM))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def migrate_postgresql(connection):
    """Apply v43 using the caller's PostgreSQL transaction context.

    Caller must ensure exclusive migration coordination and commit/rollback.
    No implicit commit occurs here.
    """
    current = connection.execute('SELECT name, checksum FROM schema_migrations WHERE version=%s', (VERSION,)).fetchone()
    if current is not None:
        if ((current['name'], current['checksum']) if hasattr(current, 'keys') else tuple(current)) != (NAME, CHECKSUM):
            raise RuntimeError('evidence migration checksum mismatch')
        column = connection.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='agent_instance_commands' AND column_name='parameters_json'").fetchone()
        if column is None:
            raise RuntimeError('evidence migration recorded without column')
        return False
    connection.execute('ALTER TABLE agent_instance_commands ADD COLUMN IF NOT EXISTS parameters_json TEXT')
    connection.execute('INSERT INTO schema_migrations(version,name,checksum) VALUES (%s,%s,%s)', (VERSION, NAME, CHECKSUM))
    return True


def apply_evidence_migration(connection, backend_name):
    """Apply version 43 in an explicit transaction, with rollback on failure.

    Intended for controlled deployment orchestration; not auto-run on startup.
    """
    name=str(backend_name).lower()
    if name == 'sqlite':
        if connection.in_transaction:
            raise RuntimeError('sqlite migration requires an independent transaction')
        return migrate_sqlite(connection)
    if name in ('postgres', 'postgresql'):
        with connection.transaction():
            return migrate_postgresql(connection)
    raise ValueError('unsupported migration backend')
