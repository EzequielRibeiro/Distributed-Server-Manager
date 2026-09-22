# Capivara DSM 2.0.114

## Customer danger-zone deletion

This release fixes the Customer instance **Zona de perigo** flow when the delete controls do not initialize even though the authenticated account has `instance.delete`.

- Reuses the authenticated workspace overview already loaded by the main Customer instance page.
- Renders delete controls idempotently during workspace refreshes.
- Keeps a fallback workspace lookup when the shared overview is not yet available.
- Displays initialization failures in the danger-zone surface instead of failing silently.
- Preserves the existing explicit confirmation, permission checks, optional final backup, Controller vault workflow, and Agent-owned removal queue.

## Validation

- PR #781: restore Customer danger-zone instance deletion.
- PR #781 completed Customer Instance Workspace v2, Browser Session Security, Customer Workspace Functional Deployment, database baseline gates, release readiness, distributed E2E, and CI successfully.
- Post-merge main validation for commit `5655715f8316279bb4b8c0062ae9e017da421d51` completed successfully, including CI and Customer Instance Workspace v2.
