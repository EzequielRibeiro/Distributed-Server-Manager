# Capivara DSM 2.0.107

Minecraft content-provider, plugin discovery, and upload UX release.

## Highlights

- Adds **Automatic** Minecraft content discovery with **Modrinth → CurseForge → external upload** fallback.
- Adds `.mrpack` external import with Minecraft version, loader, hash, and server-required component validation.
- Detects CurseForge export ZIPs and explains when a 3rd Party API Key is required.
- Fixes Modrinth plugin discovery for multi-type projects using `all_project_types:plugin` semantics.
- Restores discovery of compatible plugins such as VoteMe on Youer 1.21.1 with Bukkit/Spigot compatibility.
- Adds real upload progress with percentage and transferred bytes.
- Changes **Enviar** to **Cancelar envio** while an external upload is active.
- Adds a server-side upload cancellation endpoint and terminal `cancelled` transfer state.
- Prevents late Agent acknowledgements from resurrecting cancelled transfers.
- Removes temporary Controller spool files when a cancellation is confirmed.
- Fixes customer instance asset cache-busting so the latest content UI is loaded.

## Validation

PRs #750, #752 and #753 passed their relevant CI, Universal Content, Minecraft Modpacks, Customer Workspace, E2E, release-readiness, security and database gates.
