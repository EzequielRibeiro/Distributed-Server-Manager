# Capivara DSM 2.0.39

Patch release following Capivara DSM 2.0.38 to close a Hybrid legacy port-backfill deadlock observed during the real Palworld rollout on `horizon-server`.

## Hybrid reservation reconciliation

- Separate the network reservation contract from Catalog `network.apply` coverage during legacy port reconciliation.
- Keep `PortProfile.from_mapping()` strict for Catalog application validation.
- Add an explicit reservation-only parser used by `reconcile_instance_ports()` so roles consumed by a game Runtime Profile can still be reconciled safely.
- Preserve validation of allocation mode, block size, role names, protocols, offsets, bind addresses, active Agent ranges, cross-instance collisions and unmanaged socket occupancy.
- Preserve Controller/database authority: no ports are synthesized locally in the Agent.
- Preserve fail-closed behavior and perform no lifecycle start/restart as part of the backfill.

For the existing Palworld compatibility case anchored at UDP 24010, the authoritative reservation set remains:

- `game=24010/udp`
- `rcon=24011/tcp`
- `rest_api=24012/tcp`

The Palworld Catalog applies the public `game` role directly, while `rcon` and `rest_api` are consumed by the Palworld Runtime Profile/configuration path. Their absence from Catalog `network.apply` must therefore not prevent reservation reconciliation.

## Regression coverage

The new regression reproduces the rollout state directly:

- Catalog `network.apply` references only `game`;
- the Controller database already contains all three Palworld reservations;
- the local RuntimeSpec is still eligible for backfill/migration;
- reservation reconciliation returns the exact existing 24010/24011/24012 block without probing occupancy for already-persisted roles;
- strict Catalog parsing still rejects unapplied reserved roles where that strict contract is intentionally requested;
- reservation parsing still rejects invalid block geometry.

The P10 Agent Network and Port Pool workflow now compiles and executes this regression explicitly.

## Validation

Validated through PR #417 with successful:

- P10 Agent Network and Port Pool, including the new regression;
- CI Gate, including Python validation, real Linux installation smoke, updater tests, Catalog v2, reproducible release build, Linux/Windows Agent packages and Phase 22 E2E;
- Final Customer Distributed E2E;
- PostgreSQL Baseline v2 Isolated Deployment;
- Customer Workspace Functional Deployment;
- Release Readiness and supporting audit/observability gates.

## Release scope

This release contains the fix merged through:

- #417 — allow Hybrid port backfill for runtime-managed roles.
