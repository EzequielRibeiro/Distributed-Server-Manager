# Capivara DSM 2.0.47

Release that consolidates the post-2.0.46 runtime, CLI, content, firewall and lifecycle hardening now present on `main`.

## Instance lifecycle arbitration

- allow only one active `start`, `stop` or `restart` command per instance;
- repeated identical lifecycle requests reuse the active `command_id`;
- contradictory lifecycle requests fail with `lifecycle_operation_in_progress` and HTTP 409;
- serialize lifecycle arbitration per instance on PostgreSQL/MySQL/MariaDB and atomically on SQLite;
- keep Dashboard lifecycle controls disabled while a request is in flight and refresh authoritative runtime state before unlocking.

## Runtime and network hardening

- preserve native managed firewall reconciliation and per-instance exposure ownership;
- retain runtime reconciliation before lifecycle actions;
- expand external Controller-Agent lifecycle coverage and native firewall validation;
- keep independent instances isolated during runtime operations.

## CLI and legacy cleanup

- make `cap` the canonical public CLI;
- remove packaged `bin/dsm` and `dsm-compat` compatibility entry points;
- remove retired shell workers and projections that are no longer part of the supported runtime path;
- tighten release/install contracts around the canonical CLI and current service topology.

## Universal content

- introduce the versioned content-provider contract and provider capability advertisement;
- add Steam Workshop content provider support for Linux and Windows runtime paths;
- strengthen content preflight and cross-platform provider tests.

## Validation

This release includes dedicated regression coverage for lifecycle arbitration, HTTP 409 conflicts, Dashboard lifecycle gating, CLI unification, managed firewall behavior, content providers, update-manager behavior and release readiness.

There is no intentional database migration in this release. Rollout remains a separate operator action after publication.
