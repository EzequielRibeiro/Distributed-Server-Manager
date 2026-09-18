# Capivara DSM 2.0.65

Release focused on managed-content reliability after 2.0.64: Hybrid parity, Steam Workshop cache correctness and observability, runtime-declared activation capabilities, and safe customer activation for DayZ and Project Zomboid.

## Highlights

- Hybrid Agent managed-content reconciliation is restored to parity with external Agents, including content processing in the embedded worker and publication of Hybrid Agent log metadata for observability.
- Customer managed-content remains visible whenever the selected runtime supports managed content, even when the current instance has no installed assignments yet.
- Linux Steam Workshop acquisition now detects common Steam cache layouts instead of assuming a single SteamCMD path.
- Steam Workshop artifacts are cached by canonical Controller-resolved revision, allowing multiple instances to reuse the same revision without re-downloading it.
- Workshop revision cache retention is lossless by default. When bounded retention is explicitly enabled, Controller-protected rollback revisions are never pruned.
- Concurrent requests for the same Workshop revision are serialized with a filesystem lock so only one SteamCMD download fills the shared cache.
- Agents publish Workshop cache inventory and hit/miss/download metrics through normal heartbeat/Hybrid observability.
- DayZ customer content activation is configurable without exposing raw process arguments. The runtime declares supported modes and the Agent remains authoritative for native `-mod=` and `-serverMod=` projection.
- RuntimeDefinition now owns generic content activation capabilities, so future runtimes can declare supported modes without game-specific Dashboard logic.
- Project Zomboid Workshop content uses the same generic activation contract and requires a validated Mod ID before activation. Until configured, the assignment remains installed but disabled.
- Revision-aware Workshop snapshots are now fail-closed: the Agent verifies the local `appworkshop_<AppID>.acf` item `timeupdated` exactly matches the requested revision before caching bytes under that revision.

## Included changes

- PR #590 — Hybrid Agent log observability parity.
- PR #592 — keep customer managed-content tab visible for supported runtimes.
- PR #593 — restore managed-content reconciliation in Hybrid mode.
- PR #594 — detect common Linux Steam Workshop cache layouts.
- PR #595 — revision-aware Steam Workshop shared cache.
- PR #596 — safe/lossless Workshop revision retention.
- PR #597 — protect Controller rollback revisions from cache pruning.
- PR #598 — serialize concurrent same-revision Workshop downloads.
- PR #599 — expose Workshop cache inventory and hit/miss/download observability.
- PR #600 — customer-selectable DayZ `mod` / `server-mod` activation.
- PR #601 — generic runtime-declared content activation capabilities.
- PR #602 — safe Project Zomboid Workshop activation with required Mod ID.
- PR #603 — verify Steam Workshop manifest revision before creating revision snapshots.

## Operational flow

The managed-content path is now:

`Customer/Admin → Controller/RBAC → provider resolution → canonical revision → Agent shared cache → manifest revision verification → U7 scan → instance-scoped materialization → runtime-declared activation → Agent-native projection → maintenance/restart → Doctor/readiness → persisted reconciled state`.

Customer input never becomes raw command-line or filesystem authority. Adapters, managed paths, provider identity and executable semantics remain server/Agent-owned.

## Compatibility and upgrade notes

- This is a patch release after 2.0.64. No new database migration is introduced by the changes listed above.
- Controllers and Agents should be upgraded to the same release before relying on the new activation/cache semantics.
- Existing legacy Workshop assignments without `artifact.revision` retain their previous acquisition behavior; new revision-aware assignments use exact manifest verification.
- Cache pruning remains disabled by default. If `CAPIVARA_WORKSHOP_CACHE_REVISIONS` is configured, the minimum effective bound is two revisions and Controller-protected rollback revisions are preserved.
- Project Zomboid Workshop assignments that require a Mod ID remain disabled until that identifier is configured through the customer activation surface.
- No direct changes are applied to an active `/opt/dsm` installation by release preparation itself; deployment continues through the normal Capivara updater.
