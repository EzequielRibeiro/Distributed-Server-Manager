# Capivara DSM 2.0.93

Corrective release for live instance telemetry on the Controller instance cards.

## Fixes

- Fixes the player count displayed on `servers.html` for Agent-owned game instances.
- Projects the latest canonical `instance_telemetry_samples` into the Controller Runtime list/detail views.
- DayZ player count now uses the live A2S-derived `players_online` and `players_max` values instead of falling back to a false zero when legacy runtime files do not contain metrics.
- Instance cards also consume canonical CPU and memory telemetry.
- Missing telemetry is displayed as unavailable instead of being silently converted to zero.
- Stale telemetry is not exposed as live when the owning Agent is offline or unavailable.
- Refreshes the `servers.js` asset revision.

## Validation

- PR #716 passed all 20 GitHub workflow gates.
- PostgreSQL, MySQL and MariaDB isolated baseline gates passed.
- Final Customer Distributed E2E and M10 Final E2E Release Validation passed.
- Direct DayZ A2S reproduction on the Horizon host returned 1 / 32 players before the Controller projection fix.
