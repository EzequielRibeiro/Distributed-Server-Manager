# Capivara DSM 2.0.108

Modrinth plugin resolution compatibility fix release.

## Fixes

- Fixes installation of Modrinth plugins whose project is exposed as `project_type=mod`.
- Removes the fragile project-level category gate for plugin installation.
- Validates compatibility using the concrete Modrinth version's Minecraft version and loaders.
- Restores managed installation of plugins such as LuckPerms on compatible Bukkit/Paper/Spigot runtimes.
- Keeps incompatible mod projects rejected when no plugin-compatible version exists.

- Adds privileged Minecraft Java RCON console execution for Hybrid Agents without exposing RCON credentials to the unprivileged worker.
- Restores `list`, `help` and other Minecraft console commands through the customer/controller workspace.
- Preserves console text selection during unchanged background refreshes instead of rebuilding the DOM every safety poll.
- Removes literal Minecraft legacy `§` formatting codes from displayed console text.

## Validation

- PR #756 validated LuckPerms resolution against Modrinth for Minecraft 1.21.1.
- Added positive and negative regression coverage for Modrinth plugin resolution.
- PR #756 passed CI, Universal Content Platform, Universal Content E2E, M8 Universal Mod Management and Capivara 2.0 Release Readiness.
