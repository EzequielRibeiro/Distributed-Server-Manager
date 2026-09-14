# Capivara DSM 2.0.54

Maintenance and platform release focused on distributed Agent update reliability, Hybrid lifecycle correctness, Minecraft catalog resolution and the Universal Content Platform.

## Highlights

- Hybrid Agents are now explicitly managed by the Controller update lifecycle. Remote Agent rollout controls are disabled for Hybrid nodes, the installed Controller version is projected into Agent update state, and legacy Hybrid rollouts are reconciled instead of remaining indefinitely in `planned`.
- Linux Agent updates can persist `/etc/capivara-agent/agent.json` under the hardened systemd sandbox. The updater also refreshes its core service units transactionally and preserves the original failure when rollback itself encounters an error.
- Remote provisioning accepts complete capability-based Agent port inventories such as `linux-iproute2` instead of requiring the legacy `source=ss` marker.
- Minecraft customer version/build selection now uses the canonical resolver contract for Forge, NeoForge, Fabric, Quilt, Purpur, SpongeVanilla, Youer and the other published runtimes, including resolvable recommendations and preservation of the selected runtime build.
- Universal Content gains Customer-scoped external upload quarantine, Minecraft Java activation adapters, and canonical Modrinth/CurseForge provider resolution with Controller-side compatibility and checksum validation.

## Included changes

- PR #481 — canonical Minecraft version resolvers in the customer selector.
- PR #482 — universal external content upload and Agent quarantine flow.
- PR #483 — canonical recommended Minecraft build selection.
- PR #485 — preserve the customer-selected Minecraft runtime build.
- PR #487 — recommend only resolvable Minecraft versions.
- PR #494 — rebaseline Universal Content Platform architecture for Minecraft.
- PR #495 — Minecraft Java managed-content activation adapters.
- PR #496 — capability-based remote Agent port inventory validation.
- PR #498 — treat Hybrid Agents as Controller-managed for updates and reconcile legacy rollout state.
- PR #499 — allow the Linux Agent updater to persist Agent configuration and safely refresh core units.
- PR #500 — canonical Modrinth/CurseForge Minecraft content providers with fail-closed compatibility checks.

## Compatibility and scope

- No new database baseline migration is required by this release.
- Existing Linux Agents installed with an older updater unit may require the one-time `/etc/capivara-agent` `ReadWritePaths` drop-in before their first upgrade; Agents already repaired with that drop-in should keep it until this release is installed.
- Hybrid Agents do not receive standalone Agent rollouts; they follow the Controller installation version.
- Modrinth/CurseForge composed modpack bundles, malware verdict orchestration and the remaining Universal Content dashboard/update workflow remain outside this release.
- Controller-side port reservation and collision validation remain authoritative for distributed provisioning.
