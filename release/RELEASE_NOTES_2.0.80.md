# Capivara DSM 2.0.80

Corrective release for distributed Agent update reliability, Baseline v2 schema migration, and the native maintenance architecture.

## Existing-database migration repair

This release adds the missing Baseline v2 upgrade path for the native restart queue.

Existing installations that had already reached upgrade v14 could otherwise run newer Controller code without the required restart command table, causing remote Agent heartbeat processing to fail.

The release includes:

- Baseline upgrade v15 for the historical DayZ native restart queue;
- Baseline upgrade v16 that migrates the game-specific queue into the shared `native_restart_commands` framework;
- idempotent handling for installations where the DayZ table was already repaired manually;
- PostgreSQL, SQLite, MySQL, and MariaDB regression coverage.

## Generic multi-game native restart framework

Native maintenance is no longer modeled as one database table per game.

The Controller now uses a shared `native_restart_commands` queue carrying:

- `game_id`;
- `runtime_id`;
- `strategy`;
- typed payload/result data;
- Agent/instance ownership and lifecycle state.

DayZ remains supported through the `dayz-shutdown-messages` adapter. Future games can add native restart adapters without introducing new game-specific database tables.

The v16 migration copies existing DayZ restart records into the generic queue and retires the legacy DayZ-specific table after successful migration.

## Linux Agent incremental updater repair

The Linux Agent updater now installs every packaged `agent/common/*.py` module instead of mapping only a fixed subset.

This closes the incremental-update failure observed when an older Agent attempted to update to code that imported the newer shared `source_rcon.py` module.

Regression coverage now verifies that newly introduced shared modules are included during incremental Agent updates.

## Mixed-version transport compatibility

Controller and Agents now use the generic heartbeat contract:

- `native_restart_command`;
- `native_restart_result`;
- `native_restart_state`.

Temporary compatibility aliases remain for the previous DayZ-specific heartbeat fields so older Agents can continue communicating during staged upgrades.

## Operational cleanup

The release also contains the verified idempotent removal behavior for an Agent that no longer has the referenced local instance, allowing Controller-side instance state and port reservations to converge instead of remaining stuck in `deleting`.

## Validation

The corrective and refactoring changes passed the applicable CI matrix, including:

- CI;
- Baseline Update Reconciliation;
- PostgreSQL Baseline v2 Isolated Deployment;
- MySQL Baseline v2 Isolated Deployment;
- MariaDB Baseline v2 Isolated Deployment;
- Agent Lifecycle Integrity;
- Agent Instance Runtime;
- Windows Agent Parity;
- DayZ Native Restart;
- Maintenance Restart Framework;
- External Controller Agent E2E;
- Final Customer Distributed E2E;
- M10 Final E2E Release Validation;
- Capivara 2.0 Release Readiness.

## Upgrade

Update an existing Controller/Hybrid installation with:

```bash
sudo cap update run
```

After the Controller is upgraded successfully, remote Agents may follow their configured update channel. This release specifically contains the incremental Linux Agent updater fix required by older Agents that previously rolled back while updating.
