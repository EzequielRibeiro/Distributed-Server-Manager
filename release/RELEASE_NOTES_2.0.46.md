# Capivara DSM 2.0.46

Patch release that restores the strict read-only guarantee of `sudo cap update preflight` for SQLite Database Baseline v2 installations.

## Why 2.0.46 exists

Capivara DSM 2.0.45 introduced a public pre-maintenance readiness command:

```bash
sudo cap update preflight
```

The command was designed to download and validate the target release, inspect database compatibility and active game processes, and prove update readiness without changing the installed Capivara tree.

A post-publication audit found one violation in the SQLite path. Database Baseline v2 health validation used the normal SQLite connection against the installed database. A missing database could therefore be created by `sqlite3.connect()`. More subtly, even SQLite URI `mode=ro` is not a sufficient filesystem read-only guarantee for WAL databases because opening/reading a WAL database can create or modify `-wal` / `-shm` auxiliary files.

## Read-only SQLite validation

PR #435 changes Baseline v2 SQLite health validation so the installed database is never opened by SQLite during `database check`, which is the path used by the update preflight.

The new contract is:

- read the source database and optional WAL only as ordinary files;
- capture content-sensitive fingerprints;
- copy the main database and WAL into a temporary directory;
- verify the source fingerprints are unchanged after the copy;
- reject an active rollback journal fail-closed;
- retry briefly if the source changes while the snapshot is captured;
- validate Baseline v2 only against the temporary snapshot;
- enable `PRAGMA query_only = ON` on the temporary validation connection;
- create no database or parent directory when the configured SQLite database is missing.

Any SQLite recovery/shared-memory artifacts produced while reading the snapshot exist only in the temporary workspace and are removed afterward.

## Regression proof

The update preflight regression now proves that:

- a missing configured SQLite database leaves its parent path absent;
- a normal initialized Baseline v2 database is byte-for-byte and mtime-for-mtime unchanged by `health_check()`;
- with a live WAL connection, the installed database, `-wal` and `-shm` remain byte-for-byte unchanged;
- a rollback journal blocks validation without modifying the source tree;
- attempted SQL writes inside the temporary validation snapshot are rejected.

The full PR validation also passed Update Manager Regression, PostgreSQL Baseline v2 Isolated Deployment, Baseline Update Reconciliation, Capivara 2.0 Release Readiness, Final Customer Distributed E2E and the complete CI pipeline including the Phase 22 final E2E gate.

## Other database backends

PostgreSQL and MySQL/MariaDB continue using the existing Baseline v2 status/upgrade inspection path. That path reads schema metadata and the Baseline upgrade ledger without applying registered upgrades during `check`.

## Release scope

There is no database migration and no game-runtime feature change in 2.0.46. This patch hardens only the read-only update-readiness boundary introduced in 2.0.45.

Publishing 2.0.46 does not update any active Controller, Agent or Hybrid host. Rollout remains a separate operator-approved action.
