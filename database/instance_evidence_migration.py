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


SQLITE_COMMAND_COLUMNS = ('command_id','agent_id','instance_id','action','status','requested_by','result_json','last_error','created_at','delivered_at','completed_at','updated_at')
SQLITE_EVIDENCE_ACTION = 'systemd_lifecycle_evidence'


def _sqlite_upgrade_command_table(connection):
    """Rebuild only the known v3 command table while foreign keys are disabled."""
    definition = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_instance_commands'").fetchone()
    if definition is None:
        raise RuntimeError('instance command table missing')
    original = definition[0]
    expected = "CHECK (action IN ('status','doctor','start','stop','restart','remove'))"
    if expected not in original:
        raise RuntimeError('unknown command table schema; refuse destructive rebuild')
    indexes = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='agent_instance_commands' AND sql IS NOT NULL").fetchall()
    triggers = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='agent_instance_commands'").fetchall()
    if triggers:
        raise RuntimeError('command table triggers require explicit migration review')
    if any(not row[1] for row in indexes):
        raise RuntimeError('unsupported command table index')
    if 'parameters_json' in {row[1] for row in connection.execute('PRAGMA table_info(agent_instance_commands)')}:
        raise RuntimeError('partially migrated command table requires manual review')
    expanded = original.replace(expected, "CHECK (action IN ('status','doctor','start','stop','restart','remove','systemd_lifecycle_evidence'))")
    expanded = expanded.replace('CREATE TABLE "agent_instance_commands" (', 'CREATE TABLE agent_instance_commands_evidence_v43 (', 1)
    if expanded == original or 'agent_instance_commands_evidence_v43' not in expanded:
        raise RuntimeError('unexpected command table DDL')
    expanded = expanded.replace('    updated_at ', '    parameters_json TEXT,\\n    updated_at ', 1)
    if 'parameters_json TEXT' not in expanded:
        raise RuntimeError('missing insertion point for parameters_json')
    connection.execute(expanded)
    columns = ','.join(SQLITE_COMMAND_COLUMNS)
    connection.execute(f'INSERT INTO agent_instance_commands_evidence_v43 ({columns}) SELECT {columns} FROM agent_instance_commands')
    connection.execute('DROP TABLE agent_instance_commands')
    connection.execute('ALTER TABLE agent_instance_commands_evidence_v43 RENAME TO agent_instance_commands')
    for _, sql in indexes:
        connection.execute(sql)


def migrate_sqlite(connection):
    """Apply and track v43 in one SQLite write transaction.

    The caller must not hold an existing transaction; BEGIN IMMEDIATE serializes
    competing migrators before either reads the version row.
    """
    if connection.in_transaction:
        raise RuntimeError('sqlite migration requires an independent transaction')
    foreign_keys = connection.execute('PRAGMA foreign_keys').fetchone()[0]
    if foreign_keys:
        connection.execute('PRAGMA foreign_keys=OFF')
    try:
        connection.execute('BEGIN IMMEDIATE')
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
        _sqlite_upgrade_command_table(connection)
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise RuntimeError('foreign key validation failed after command table rebuild')
        connection.execute('INSERT INTO schema_migrations(version,name,checksum) VALUES (?,?,?)', (VERSION, NAME, CHECKSUM))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        if foreign_keys:
            connection.execute('PRAGMA foreign_keys=ON')


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
    # The consolidated PostgreSQL schema uses VARCHAR(16) plus an action CHECK.
    # Both must be widened before evidence commands can be enqueued.
    connection.execute('ALTER TABLE agent_instance_commands ALTER COLUMN action TYPE TEXT')
    constraints = connection.execute("SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid = 'agent_instance_commands'::regclass AND contype = 'c'").fetchall()
    for constraint in constraints:
        name = constraint['conname'] if hasattr(constraint, 'keys') else constraint[0]
        definition = constraint['definition'] if hasattr(constraint, 'keys') else constraint[1]
        if 'action' in str(definition).lower():
            if not name.replace('_', '').isalnum():
                raise RuntimeError('invalid constraint identifier')
            connection.execute('ALTER TABLE agent_instance_commands DROP CONSTRAINT "' + name + '"')
    connection.execute("ALTER TABLE agent_instance_commands ADD CONSTRAINT agent_instance_commands_action_evidence_check CHECK (action IN ('status','doctor','save','start','stop','restart','remove','systemd_lifecycle_evidence'))")
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
