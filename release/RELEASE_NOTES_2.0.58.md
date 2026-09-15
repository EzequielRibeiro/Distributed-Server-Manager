# Capivara DSM 2.0.58

Maintenance release that publishes the post-2.0.56 lifecycle, console, Hybrid, updater and Minecraft selector fixes together with a hardened legacy-updater release bridge.

## Highlights

- Instance console streaming survives restart lifecycle transitions in Controller and Customer views, including stale-open SSE recovery, snapshot fallback/reconnect and correct multi-line clipboard serialization.
- DayZ controlled shutdown exit 255 is represented by the runtime profile and materialized as `SuccessExitStatus=255`; persisted v6 RuntimeSpecs migrate to profile v7 through the normal reconciler while true crashes remain failures.
- Hybrid installations provision the privileged `capivara-agent` control identity idempotently so runtime profile rematerialization can recover during upgrades.
- Updater final validation is canonical `cap`-only; legacy `bin/dsm` is no longer a final-installation requirement.
- Minecraft dynamic runtime selection publishes every version from multi-version resolvers, recognizes GitHub `tag` builds, avoids redundant resolution when a unique build is already known, drops stale browser responses and leaves `Carregando builds…` cleanly on provider errors.
- The legacy updater bridge now accepts both genuinely old updater sources and modern sources that are already cap-only, while remaining fail-closed for unknown validation layouts.

## Included changes

- PR #541 — preserve Controller/Customer live console continuity across systemd lifecycle records.
- PR #542 — treat DayZ controlled exit 255 as successful shutdown through the generic RuntimeSpec contract.
- PR #544 — validate final installations as `cap`-only.
- PR #545 — migrate DayZ runtime profile v6 to v7 for existing instances.
- PR #546 — provision the Hybrid privileged control identity.
- PR #548 — recover stale-but-open console SSE streams during lifecycle operations.
- PR #550 — repair Minecraft multi-version version/build selection and stale request handling.
- PR #551 — preserve line breaks when copying multiple console log lines.
- PR #553 — make the package-only legacy updater bridge compatible with an already cap-only source tree.

## Publication note

The 2.0.57 release transaction created immutable `v2.0.57` and standalone Agent tags for its approved commit, but canonical DSM publication stopped before the GitHub Release was created because the legacy updater bridge still expected the pre-#544 validation anchor. Those tags are intentionally not moved or rewritten. 2.0.58 is the next canonical DSM release and contains the same product fixes plus the release-bridge correction.

## Compatibility and upgrade notes

- No new database migration is required.
- Hybrid upgrades reconcile the `capivara-agent` control user automatically; no manual `/opt/dsm` edits are required.
- DayZ RuntimeSpecs persisted at profile v6 migrate to v7 through normal reconciliation.
- Customer browsers receive `runtime-selector.js?v=5` after upgrade.
- Linux and Windows standalone Agent packages are generated from the same approved 2.0.58 release commit.
