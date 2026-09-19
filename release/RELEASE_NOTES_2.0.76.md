# Capivara DSM 2.0.76

Corrective release for DayZ Workshop dependency activation and hardened CLI version queries.

## DayZ Workshop dependencies

Universal Content can now resolve catalog-declared Steam Workshop dependency graphs Controller-side.

The DayZ stable runtime declares VPPAdminTools (1828439124) as requiring CF (1559212036). Installing VPPAdminTools now creates the required CF assignment automatically, validates both items against the DayZ Workshop AppID, persists the graph atomically, and sends both through the normal Agent download, YARA-X scan, activation and readiness flow.

Activation snapshots now preserve dependencies and use dependency-aware ordering. Required items are projected before dependents, while activation_order remains the ordering rule between independent items. A dependent item is excluded fail-closed if its required content is not active.

This fixes the observed runtime failure where VPPAdminTools loaded without CF and DayZ exited with:

```
Failed to load game scripts
```

## Hardened CLI version query

`cap --version`, `cap -V`, and `cap version` now read the public installation version before loading the bootstrap.

This preserves the secure `0640 capivara:capivara` permissions on `/opt/dsm/config/dsm.conf` while allowing a normal administrative shell user to query the installed version.

## Validation

PR #644 passed the complete 36-workflow matrix, including Universal Content Platform, Universal Content E2E, Windows DayZ Instance Isolation, DayZ Native Restart, Agent Instance Runtime, External Controller Agent E2E, M8, M10, CI, and Catalog Architecture.

PR #643 passed its complete affected matrix, including CLI Unification, Agent Local CLI, Update Manager Regression, Universal Content Platform, Agent Instance Runtime, Final Customer Distributed E2E, CI, and Capivara 2.0 Release Readiness.

## Included changes

- PR #644 — resolve required Workshop dependencies and enforce dependency-aware activation.
- PR #643 — make `cap --version` independent of private configuration.

## Operational recovery

After v2.0.76 is published, update the Hybrid Controller normally:

```bash
sudo cap update run
```

Then allow Universal Content reconciliation to install CF and re-apply VPPAdminTools. No manual permission changes or direct edits under `/etc/systemd/system` are required.
