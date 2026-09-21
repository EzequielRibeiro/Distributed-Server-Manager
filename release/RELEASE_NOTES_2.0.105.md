# Capivara DSM 2.0.105

Modrinth plugin discovery compatibility release.

## Fixes

- Corrects Modrinth discovery for Minecraft plugins by using the provider-native `project_type:plugin` classification instead of treating plugins as mods.
- Allows plugin projects such as VoteMe to appear in compatible searches for Youer 1.21.1.
- Keeps Modrinth discovery type-safe across `mod`, `plugin` and `modpack`.
- Makes authoritative Modrinth resolution validate the expected project type before choosing a version.
- Preserves Youer plugin loader compatibility through the existing Bukkit/Spigot provider mapping.
- Adds regression coverage for Youer 1.21.1 plugin discovery and authoritative VoteMe resolution.

## Validation

PR #746 passed all triggered checks, including:
- CI Gate / Phase 22
- Universal Content Platform
- Universal Content E2E
- M8 Universal Mod Management
- Final Customer Distributed E2E
- Capivara 2.0 Release Readiness
- Legacy Audit
- Baseline Update Reconciliation
