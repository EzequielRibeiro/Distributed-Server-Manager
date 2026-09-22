# Capivara DSM 2.0.115

## Hybrid recovery and lifecycle state reconciliation

This release hardens Hybrid mode after a production DayZ port-collision incident exposed failure-domain coupling between network reconciliation and unrelated control-plane work.

- Keeps backup processing and safe instance removal available when runtime port reconciliation is blocked.
- Preserves fail-closed behavior for unsafe runtime mutations while allowing recovery-oriented stop/remove paths.
- Reconciles `instances.status` automatically after successful `start`, `stop`, and `restart` commands for contract-valid Customer instances.
- Prevents a locally stopped instance from remaining stale as `online` in Controller persistence and blocking port relocation.
- Marks deleted-backup vault entries as failed when their source instance was already removed before the final backup completed, instead of leaving them stuck in `backup_pending`.
- Closes stale Hybrid Agent update rollouts when the embedded Controller is already newer than the rollout target, aligning installed, available, and desired versions.

## DayZ network recovery validation

Production validation on `horizon-server` confirmed the DayZ runtime with the managed network block:

- game: UDP 24000
- game_aux / Steam client port: UDP 24002
- Steam query / A2S: UDP 24003
- BattlEye reservation: UDP 24004

The DayZ A2S endpoint was verified locally and through external UDP traffic. The managed runtime reports the correct Steam server app identity files (`223350`) and the Controller/Agent lifecycle state is now consistent after restart.

## Validation

- PR #785: isolate Hybrid port-backfill failures from backup and safe removal.
- PR #786: reconcile lifecycle status, orphaned deleted-backup vault state, and stale Hybrid update rollout state.
- PR #786 completed CI, Agent Instance Runtime, Instance Lifecycle Arbitration, External Controller Agent E2E, Maintenance Restart Framework, database baseline gates, release readiness, distributed E2E, and all other triggered checks successfully.
