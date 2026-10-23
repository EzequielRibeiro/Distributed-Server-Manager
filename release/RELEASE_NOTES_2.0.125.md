# Capivara DSM 2.0.125

## Minecraft Server Pack recovery on hybrid Agent

- Adds guarded recovery for a failed, pre-swap NeoForge Server Pack migration when the original runtime is intact and the migration-specific transaction journal was never created (PR #923).
- Requires recognition of the prior permission-denied failure, registered instance root, original NeoForge launcher evidence, and absence of swap, rollback, staging and journal artifacts before releasing the outer operation barrier.
- Adds a local, root-only administrator command `sudo cap instance recover-serverpack <instance-id> --confirm <instance-id>` for eligible registered Minecraft NeoForge instances (PR #925).
- Keeps invalid or ambiguous filesystem evidence fail-closed; no automatic retry, game restart, world replacement or content publication is performed by recovery.

## Validation and deployment safeguards

- PR #923 passed 19/19 GitHub Actions workflows; PR #925 passed 31/31.
- Prior isolated Server Pack regression suite passed 218/218 tests, including new CLI permission and exact-instance confirmation tests.
- This preparation keeps `publish_release: false`; publication requires a separate release trigger after all release candidate checks pass.
- Updating the installed DSM may stop/restart managed game instances under the current updater. Do not deploy on horizon-server without a separately planned maintenance procedure.
- No Minecraft 005 recovery, retry or customer-facing Server Pack migration is authorized merely by publishing this release.
