# Capivara DSM 2.0.38

Patch release following Capivara DSM 2.0.37 to complete Controller-authoritative port backfill for existing Hybrid RuntimeSpecs and harden update success reporting.

## Hybrid legacy port backfill

- Reconcile missing instance port reservations in the Controller/Hybrid database before RuntimeSpec migration or runtime reconciliation.
- Use the canonical Catalog v2 network definition and the existing transactional `reconcile_instance_ports()` path instead of synthesizing ports locally in the Agent.
- Persist the committed bindings back into both `ports` and `profile_context.ports` in the local Hybrid RuntimeSpec.
- Keep the reconciliation fail-closed: reservation conflicts, occupied ports, incomplete Catalog identity, unavailable Controller state, or local RuntimeSpec persistence errors stop the cycle before runtime reconciliation proceeds.
- Preserve lifecycle safety: this compatibility path does not start or restart game runtimes.

For the existing Palworld compatibility case anchored at UDP 24010, the canonical profile resolves:

- `game=24010/udp`
- `rcon=24011/tcp`
- `rest_api=24012/tcp`

## Update Manager integrity

- Re-read the installed version after the target updater exits successfully.
- Refuse to record update success when the installed version does not match the selected release.
- Emit update failure and return non-zero instead of writing a false successful history entry after a cancelled or ineffective target update.

## Validation

The regression and release gates cover:

- exact Palworld RuntimeSpec bindings from Controller reservations;
- database reconciliation failure leaving the local RuntimeSpec untouched;
- idempotent already-complete reservation sets;
- network inventory -> port backfill -> Hybrid runtime reconciler ordering;
- update-manager installed-version verification;
- CI, P10 Agent Network and Port Pool, Release Readiness, PostgreSQL baseline and Final Customer Distributed E2E.

## Release scope

This release contains the fixes merged through:

- #414 — reject false updater success;
- #415 — backfill Hybrid runtime ports before reconciliation.
