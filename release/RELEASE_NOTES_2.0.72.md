# Capivara DSM 2.0.72

Corrective release for the YARA-X Baseline v2 upgrade path.

## Fix

Capivara DSM 2.0.71 introduced the YARA-X administrative operation table in the consolidated Baseline v2 schema. Existing installations already on upgrade ledger v13 therefore saw a baseline checksum change without a registered pending upgrade and the updater correctly blocked before stopping services or replacing files.

Version 2.0.72 registers Baseline v2 upgrade **14** (`yarax_admin_operations`) so existing installations can safely reconcile from v13 to the current YARA-X schema.

## Validation

- Existing v13 Baseline v2 databases are recognized as upgradeable.
- The updater preflight sees upgrade 14 as pending instead of treating the checksum change as incompatible.
- The YARA-X administrative operation table is created idempotently.
- The baseline marker is advanced only after the registered upgrade is applied.
- PostgreSQL isolated deployment, Linux E2E, Windows E2E, M10 and CI Gate passed on the fix PR.

## Included changes

- PR #635 — reconcile YARA-X Baseline v2 upgrade 14.

## Operational impact

Systems blocked while upgrading from 2.0.70 to 2.0.71 can upgrade directly to 2.0.72 with the normal updater:

```bash
sudo cap update run
```

No manual database modification is required.
