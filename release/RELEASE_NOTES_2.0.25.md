# Capivara DSM v2.0.25

Hotfix release for the Database Baseline v2 migration runtime.

## Fixed

- Aligns the real database migration path with the v2.0.24 updater preflight policy for Database Baseline v2.
- Accepts an existing database whose versioned Baseline v2 upgrade ledger is present, valid, fully reconciled, and already at the target release's latest registered upgrade version even when the consolidated baseline checksum changed between releases.
- Reconciles only the `schema_baseline` marker after validating the required live database structure; it does not replay already-applied DDL when the ledger is current.
- Preserves the normal registered-upgrade path when the ledger is behind and preserves rejection when no safe ledger/upgrade path exists.
- Adds runtime regression coverage for the exact class of state observed during the live v2.0.14 -> v2.0.24 update failure: checksum drift with a complete v5 ledger and no pending upgrades.
- Preserves the v2.0.23 rollback systemd rendering protection and the v2.0.24 target-package preflight protection.

## Upgrade note

v2.0.24 is superseded for installations affected by Baseline v2 checksum drift. Upgrade directly to v2.0.25.
