# Capivara DSM 2.0.126

## Minecraft 005 Server Pack recovery

- PR #932: safely recover a previously blocked, pre-swap NeoForge migration when the registered Agent instance has no build_id.
- An unambiguous installed NeoForge library version must exist, and canonical runtime launcher verification must succeed. Multiple versions, bad symlinks, and launcher inconsistencies remain blocked.
- Operator-invoked recovery releases the stale failed-operation lock only after filesystem and original runtime verification. It does not upgrade the Minecraft modpack or restart the game.
- PR #932 passed 19/19 GitHub workflows and 11 targeted recovery regressions.
- Earlier privileged staging implementation from 2.0.124 remains in place.

## Deployment safety

- Release preparation does not publish, deploy, or invoke recovery.
- Do not update horizon-server without planning for the current updater's managed-game drain and restart behavior.
- Preserve Minecraft 005 world, instance state and failed journal evidence until successful guarded recovery.
- Customer-area Server Pack update requires a separate supervised functional test.
