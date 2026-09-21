# Capivara DSM 2.0.103

Minecraft Java private-runtime repair hotfix.

## Fix

- Repairs stale instance-private Minecraft Java runtimes after a failed or corrected provider installation.
- Adds an explicit seed-directory `overlay` mode that refreshes provider-owned files into an existing private runtime while preserving target-only instance data such as worlds and runtime-generated configuration.
- Minecraft Java enables this overlay on Linux and Windows, and profile versions are bumped so existing runtime specs reconcile automatically.
- Fixes the v2.0.102 follow-up failure where shared Youer game-data contained a valid `server.jar`, but the previously created private runtime still lacked `runtime/server.jar`, causing `Unable to access jarfile` at service startup.

## Validation

- Reproduced the stale private runtime using the same extracted Youer tree that caused the v2.0.101 integrity failure.
- Overlay repair restored the 123 MiB `server.jar` while preserving a target-only `world/level.dat` file unchanged.
- PR #739 passed all 32 triggered workflows, including CI, Agent Instance Runtime, Agent Game Data, Windows Agent Parity, M10 Final E2E Release Validation and External Controller Agent E2E.
