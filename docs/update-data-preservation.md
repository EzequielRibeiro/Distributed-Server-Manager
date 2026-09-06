# Update backup and game data

The pre-update archive protects the application, configuration and operational
metadata. The database is backed up separately using its native backend. Active
game instances are checked before backup; a preflight refusal never restores the
database or replaces installation files. Application services are stopped before
the filesystem/database snapshots and restored if preparation fails.

The following data trees are excluded from the archive and disk-space estimate:

- `instances`
- `game-data`
- `runtime/hybrid-agent-state`
- `runtime/hybrid-instance-storage`

During activation they are renamed into `<INSTALL_DIR>.update-preserved`, then
reattached to the new installation. This uses the same filesystem, preserving
inodes, ownership and permissions without a second copy. Product permission
updates do not traverse these trees. Rollback restores application files and the
database while retaining the current game data. It does not rewind saves.

Independent instance backups (preferably incremental and stored separately) are
still required. This update archive alone cannot recover lost worlds or game
files. External storage roots are not backed up by this mechanism. Direct
mountpoints/cross-filesystem moves and a symlinked runtime root are rejected
before backup rather than silently falling back to a large copy.

## Interrupted updates

Handled errors/signals after file replacement trigger rollback when a valid
backup exists. A failure before replacement only restarts captured services.
`--no-backup` still disables automatic rollback.

After SIGKILL or power loss, never delete `<INSTALL_DIR>.update-preserved` or
`<INSTALL_DIR>.update-restore`. A new update refuses to run while either exists.
With services and game instances stopped, recover the matching application and
database backup first, retaining those directories outside the installation.
Reattach each protected tree from `.update-preserved` to its exact relative path
in the installation. If both locations contain data, inspect them and resolve
the conflict; do not overwrite either. Only remove empty recovery directories
after confirming all protected paths and the recovered application/database.

Updates that migrate save formats require a separate backup/migration plan for
the affected instance data; ordinary application rollback cannot undo them.
