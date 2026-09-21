# Capivara DSM 2.0.104

Minecraft content capability consistency release.

## Fixes

- Prevents the Customer Content workspace from displaying content types that the selected runtime does not actually support.
- NeoForge, Fabric, Forge and Quilt now expose only Mod/Modpack discovery where declared by the RuntimeDefinition; Plugin is no longer shown from stale or inconsistent contract sections.
- Paper, Purpur, Folia and SpongeVanilla remain Plugin-only.
- Arclight exposes Mod + Plugin, but Mod discovery remains fail-closed until a loader-base mapping is explicitly proven; Mod can still use External Upload when the contract permits it.
- Youer exposes Mod + Plugin + Modpack.
- Vanilla Java and Bedrock Vanilla do not expose managed content sections.
- Searchable content types are now separated from upload-only types, avoiding empty provider selectors.
- Runtime cards now describe Votifier according to the runtime ecosystem: Mod, Plugin or Mod/Plugin instead of assuming Bukkit plugin semantics.
- Adds a 12-runtime Minecraft regression matrix covering managed content capabilities.

## Validation

PR #744 passed all triggered checks, including:
- CI Gate / Phase 22
- PostgreSQL / MySQL / MariaDB
- M8 Universal Mod Management
- M9 Minecraft Modpacks
- M10 Final E2E
- Linux / Windows final E2E
- Customer Workspace functional deployment

