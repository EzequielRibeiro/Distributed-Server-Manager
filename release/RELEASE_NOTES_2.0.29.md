# Capivara DSM 2.0.29

Patch release for safe application updates on hosts with large instance storage, including Hybrid installations.

## Fixed

- Reject updates with active game instances before creating the pre-update backup.
- Do not restore the database or replace installation files after a preflight refusal. Rollback is gated on file replacement having started.
- Stop application services before filesystem/database snapshots and restore captured services if preparation fails.

## Data preservation

- Exclude `instances`, `game-data`, `runtime/hybrid-agent-state` and `runtime/hybrid-instance-storage` from the update archive.
- Preserve these trees with same-filesystem renames during activation and rollback, avoiding full copies and preserving inode identity, ownership and permissions.
- Exclude protected trees from update disk estimates and recursive product permission changes.
- Reject conflicting recovery data, stale recovery directories, direct mountpoints/cross-filesystem moves and a symlinked runtime root before destructive changes.

## Operational notes

- Stop game instances cleanly before updating; this release does not enable updates while games are running.
- Keep independent instance backups. The application update archive cannot restore lost worlds or game files, and application rollback does not rewind saves.
- Following power loss or SIGKILL, retain `.update-preserved` and `.update-restore` directories and follow `docs/update-data-preservation.md` before retrying.
- No database schema or game runtime definition changes in this patch.

## Validation

PR #370 passed all 14 checks, including Linux Update Manager regressions. Behavioral tests cover archive exclusions, inode preservation, rollback, preflight refusal, partial movement, corrupt backups and conflicting recovery state.
