# Capivara DSM 2.0.95

Corrective release for safer DSM maintenance updates with active managed game instances.

## Fixes

- Removes the operational requirement to manually stop every Capivara-managed game instance before `cap update run`.
- The updater now records active `capivara-instance-*.service` units, drains them automatically before the maintenance transaction and restores only the units that were active before the update.
- Controller and Worker services are stopped after managed game instances are drained.
- The strict Process Guard is re-run after the drain to ensure no unmanaged game runtime remains before backup or file mutation.
- Read-only `cap update preflight` now reports managed active instances as eligible for automatic drain instead of failing.
- Unmanaged runtimes remain fail-closed and still block the update.
- If an update fails before file replacement or rolls back after mutation, previously active managed game instances are restored.

## Validation

- PR #720 passed all 14 GitHub workflow gates.
- Update Manager Regression passed.
- Final Customer Distributed E2E passed.
- Capivara 2.0 Release Readiness passed.
- CI passed, including real Linux installation, updater tests, reproducible release build and Phase 22 final E2E.
- Local update regression covered preflight, protected data, backup/rollback, CLI and functional drain/restore of multiple managed instance units.
