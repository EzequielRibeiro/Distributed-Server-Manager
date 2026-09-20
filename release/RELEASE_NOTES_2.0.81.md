# Capivara DSM 2.0.81

Corrective release for legacy Linux Agent incremental updates.

## Legacy updater compatibility

Agents on older versions such as 2.0.59 apply a new package using the updater that is already installed on the Agent. That legacy updater dynamically copies every `agent/runtime/**/*.py` file, but only knew about `agent/common/identity.py`.

As a result, newer shared modules such as `source_rcon.py` were present in the published package but were never copied to the installed Agent. The new runtime then failed before its first post-update heartbeat and the updater correctly rolled back.

This release adds a compatibility bridge:

- all shared `agents/common/*.py` modules remain packaged in the canonical `agent/common` location;
- they are additionally mirrored into `agent/runtime/compat_common/`;
- the Linux Agent adds that compatibility directory to its import path when present;
- current installers and updaters continue to use the canonical `agent/common` layout.

This makes old-to-current incremental updates bootable without requiring the old updater to understand the newer shared-module layout.

## Regression coverage

The Linux Agent package test now simulates the exact v2.0.59 updater behavior:

- copy every runtime Python module;
- copy only `common/identity.py`;
- boot/import the new Agent runtime;
- verify imports of `native_maintenance` and `source_rcon` succeed.

The applicable CI matrix passed before merge, including CI, Catalog Architecture, Agent Local CLI, Agent Game Data, Agent Instance Runtime, External Controller Agent E2E, Customer Instance Workspace v2, M10 Final E2E Release Validation, DayZ Native Restart, M7 Native Maintenance, Universal Content Platform, Update Manager Regression, and Release Readiness.

## Upgrade

For affected Agents still on 2.0.59, do not target 2.0.80 again. Upgrade them to 2.0.81 after the Controller sees the published stable release.
