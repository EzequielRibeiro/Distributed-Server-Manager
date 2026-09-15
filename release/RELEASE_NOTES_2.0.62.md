# Capivara DSM 2.0.62

Maintenance release focused on customer Minecraft runtime selection and server settings materialization.

## Highlights

- Minecraft dynamic version/build selection no longer performs hundreds of visible `<select>` mutations when a runtime exposes a large build set. NeoForge 1.21.1 currently exposes 243 builds; options are now assembled off-DOM and committed atomically.
- Customer catalog version/build requests now have a 15-second browser-side timeout. A stalled provider/request leaves `Carregando builds…` with a recoverable error instead of hanging indefinitely.
- The runtime selector cache key advances to `runtime-selector.js?v=6`, ensuring clients receive the corrected selector implementation after upgrade.
- Materialized server property files now deduplicate managed keys, avoiding repeated configuration entries across subsequent saves/reconciliation.

## Included changes

- PR #563 — deduplicate materialized server properties.
- PR #564 — prevent stalls in large Minecraft build selectors, including NeoForge 1.21.1, and add bounded catalog request handling.

## Compatibility and upgrade notes

- No database migration is required.
- The NeoForge resolver contract is unchanged; Minecraft 1.21.1 continues to resolve the current recommended NeoForge build through the canonical Maven resolver.
- The change is browser/UI resilience only for build rendering and request timeout; Agent installation semantics remain unchanged.
