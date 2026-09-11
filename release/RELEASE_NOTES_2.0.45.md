# Capivara DSM 2.0.45

Patch release that adds a read-only rollout readiness gate to the public Capivara CLI.

## Read-only update preflight

PR #433 introduces:

```bash
sudo cap update preflight
```

The command is designed to be executed before an operator opens an update maintenance window. It downloads the latest stable DSM package and official SHA256 into an isolated temporary workspace outside `/opt/dsm`, validates the archive, and then executes the preflight contract shipped by the target release itself.

The target-release contract validates:

- installed and target SemVer identity and upgrade direction;
- required target update components;
- DSM runtime user, group and home;
- preservation feasibility for `instances`, `game-data`, `runtime/hybrid-agent-state` and `runtime/hybrid-instance-storage`;
- absence of unfinished update/rollback state;
- free disk capacity for the update transaction;
- database compatibility using the target release's `process-guard.sh`;
- absence of active game instances before maintenance begins.

## Read-only boundary

The preflight does not:

- stop or restart services;
- terminate game instances;
- execute database migrations;
- create the pre-update backup;
- write the installed update cache;
- replace `/opt/dsm`;
- modify systemd units;
- record update success/history.

Release package and checksum downloads exist only in a temporary workspace and are removed on exit. The normal `update.sh` Process Guard remains authoritative immediately before mutation, so a game instance started after preflight still blocks the real update.

## CLI and regression coverage

The feature is exposed through the canonical `cap` CLI while the deprecated `dsm` compatibility path reaches the same dispatcher contract. CI coverage proves:

- `cap update preflight` routing;
- the preflight wrapper does not use the installed update cache or mutating update pipeline;
- archive validation occurs before target extraction/preflight;
- stable release-channel enforcement;
- valid upgrade acceptance;
- same-version and downgrade rejection;
- incomplete target package rejection;
- existing updater, installation, package and Phase 22 gates remain green.

A canonical operator runbook is included at `docs/UPDATE_PREFLIGHT.md`.

## Validation

PR #433 completed successfully with:

- Capivara 2.0 Release Readiness;
- Update Manager Regression;
- CI, including real Linux installation smoke;
- updater CLI regression with the new preflight contract;
- reproducible release build;
- Linux and Windows Agent package tests;
- Agent Instance Runtime;
- Final Customer Distributed E2E;
- Phase 22 final end-to-end gate;
- CLI Unification, Baseline Update Reconciliation, P0-D and P10 gates.

## Release scope

This patch has no database migration and does not change game runtime behavior. Its production change is the new update-readiness boundary and supporting documentation/tests.

## Operational boundary

Publishing 2.0.45 does not update an active Controller or Agent installation. Rollout to `horizon-server` or any `/opt/dsm` installation remains a separate operator-approved action.
