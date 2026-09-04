# Capivara DSM v2.0.24

Hotfix release for Database Baseline v2 update preflight compatibility.

## Fixed

- Accepts a Database Baseline v2 installation when the versioned upgrade ledger is present, valid, fully reconciled, and already at the target release's latest registered upgrade version even when the consolidated baseline checksum changed between releases.
- Preserves rejection for missing tables, baseline identity mismatch, upgrade errors, unknown pending upgrades, or target upgrade-version mismatches.
- Keeps the v2.0.23 rollback systemd rendering protection in the packaged updater so restored units cannot retain `{{DSM_USER}}` / `{{DSM_GROUP}}` placeholders.
- Adds release-build regression validation for the exact PostgreSQL preflight state observed during the failed v2.0.23 update: ledger present, version 5/latest 5, no pending upgrades, checksum mismatch.

## Upgrade note

v2.0.22 and v2.0.23 are superseded. Upgrade directly to v2.0.24.
