# Capivara DSM 2.0.57

Maintenance release focused on instance lifecycle reliability, live console continuity, Hybrid runtime repair, updater correctness and Minecraft runtime selection.

## Highlights

- Instance console streaming now survives restart lifecycle transitions end-to-end. Controller and Customer consoles accept systemd lifecycle records, detect an EventSource that remains open but stops delivering useful console payloads, recover with snapshot + reconnect, and preserve line breaks when users copy multiple log lines.
- DayZ controlled shutdown is now represented by the runtime profile with `success_exit_statuses=[255]`, materialized as `SuccessExitStatus=255`, and existing v6 RuntimeSpecs migrate to profile v7 automatically. Real crash states such as SIGSEGV remain failures.
- Hybrid hosts now provision the privileged `capivara-agent` control identity idempotently, allowing profile migration and privileged materialization to recover existing installations through the updater.
- Updater final validation is fully `cap`-only and no longer rejects a valid installation because legacy `bin/dsm` is absent.
- Minecraft dynamic runtime selection now publishes every version exposed by multi-version resolvers, recognizes GitHub release `tag` builds directly, avoids redundant remote resolution for a unique build, discards stale browser responses and exits the `Carregando builds…` state cleanly on provider errors.

## Included changes

- PR #541 — keep live console output flowing across systemd stop/start lifecycle records and restore Controller live-console assets.
- PR #542 — model DayZ controlled exit 255 as a successful shutdown through the generic RuntimeSpec/systemd materializer contract.
- PR #544 — make updater final installation validation accept the canonical `cap`-only layout.
- PR #545 — migrate persisted DayZ RuntimeSpecs from profile v6 to v7 so `SuccessExitStatus=255` reaches existing instances.
- PR #546 — provision the Hybrid `capivara-agent` privileged control identity required by the materializer.
- PR #548 — recover an SSE console stream that remains open but becomes stale during `start`/`restart`, without reconnecting quiet servers outside lifecycle operations.
- PR #550 — repair Minecraft version/build selection for multi-version resolvers such as GitHub-backed runtimes and add browser stale-request/error recovery.
- PR #551 — preserve real line breaks when copying multiple console log lines in Controller and Customer surfaces.

## Compatibility and upgrade notes

- No new database migration is required by this release.
- Hybrid upgrades reconcile the missing `capivara-agent` control user automatically; manual edits under `/opt/dsm` are not required.
- DayZ instances persisted with runtime profile v6 are expected to migrate to v7 through the normal reconciler and rematerialize their systemd unit.
- The Customer runtime selector cache key advances to `runtime-selector.js?v=5`, ensuring browsers fetch the corrected Minecraft selector after upgrade.
- Linux and Windows Agent packages are published from the same approved release commit by the canonical release workflow.
