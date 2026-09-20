# Capivara DSM 2.0.92

Corrective release for Hybrid Minecraft Java provisioning.

## Fixes

- Fixes the Hybrid Controller ownership of per-instance private control state used during runtime reconciliation.
- Keeps `.dsm` private with mode `0700`, without granting the game runtime account access to Agent control state.
- Uses the configured Hybrid DSM service account as the control-state owner while preserving `capivara-agent` as the standalone Linux Agent fallback.
- Prevents successful Minecraft Java materialization and firewall reconciliation from being rolled back during `initial_reconcile` because the Hybrid worker cannot write content-activation manifests.

## Validation

- PR #714 passed all 21 GitHub workflow gates, including CI, Agent Instance Runtime, External Controller Agent E2E, Final Customer Distributed E2E and M10 Final E2E Release Validation.
- Focused materialization, runtime-secret, Hybrid content-activation and Minecraft Java RCON regressions also pass on the Horizon test host.
