# Capivara DSM 2.0.124

## Minecraft Server Pack migration on hybrid Agent

- Delegates Server Pack input preparation, candidate staging, atomic runtime switch, commit and rollback to the constrained privileged materializer (PR #920).
- Preserves runtime ownership and ACL access for newly installed mod jars during privileged staging.
- Enforces registered-instance systemd inactivity before privileged migration operations; rejects foreign Agent identities, mismatched instance IDs and unsafe storage roots.

## Validation

- PR #920 passed all 24 GitHub Actions workflows; 210 Server Pack regression tests and 34 privileged-materializer tests passed on horizon-server.
- Isolated NeoForge 26.1.2.94 to 26.1.2.109 filesystem migration and rollback passed under systemd.
- A disposable NeoForge 26.1.2.109 runtime with real ATM11 mods booted successfully using Java 25 and was stopped under a memory-limited transient systemd unit.

## Deployment safeguards

- Release publication is explicit and guarded by the release readiness contract, immutable release identity checks and published-asset smoke tests.
- Installing/updating DSM may restart active managed game instances. Do not run `cap update run` on horizon-server without separate maintenance authorization.
- Minecraft 005 customer-triggered Server Pack migration remains reserved for post-release verification; no automatic update of that instance is authorized.
