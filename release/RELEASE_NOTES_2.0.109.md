# Capivara DSM 2.0.109

Minecraft managed-content activation compatibility release.

## Fixes

- Prevents the Customer content UI from implicitly selecting `Mod` when adding Minecraft content.
- Requires explicit selection of content type before search/install.
- Distinguishes Bukkit/Spigot plugins from NeoForge mods in Minecraft content search results.
- Preserves the discovered `content_type` when installing Modrinth content.
- Supports provider-scoped Minecraft content IDs such as `modrinth:Vebnzrzj`.
- Projects provider-scoped IDs to portable native filenames using percent-encoding.
- Preserves canonical provider IDs in database and Agent state while using filesystem-safe native projection names.
- Applies the provider-scoped projection fix consistently on Linux and Windows Agents.
- Restores native activation of LuckPerms Bukkit on Youer as `plugins/capivara-modrinth%3AVebnzrzj.jar`.

## Validation

- PR #760 passed 27 checks and added regression coverage for explicit Minecraft content-type selection.
- PR #761 passed 29 checks and added Linux/Windows regression coverage for provider-scoped Minecraft content IDs.
- Verified LuckPerms resolution for Minecraft 1.21.1:
  - Plugin -> `LuckPerms-Bukkit-5.5.71.jar`
  - Mod -> `LuckPerms-NeoForge-5.4.140.jar`
- Verified managed-content state and activation snapshot preserve `modrinth:Vebnzrzj` as the canonical content ID.
