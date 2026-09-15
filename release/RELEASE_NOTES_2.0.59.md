# Capivara DSM 2.0.59

Maintenance release focused on Minecraft NeoForge runtime build selection responsiveness.

## Highlights

- NeoForge Maven discovery now marks the latest build for each Minecraft version directly in the canonical resolver list.
- `/api/catalog/builds` preserves provider `recommended` / `current` metadata and skips a second remote resolve when exactly one recommended build is already known.
- Minecraft Java NeoForge 1.21.1 still exposes all 243 discovered builds, with `21.1.250` recommended, while observed catalog response time drops from about 4.47 seconds to about 1.03 seconds.
- Providers that do not publish a recommendation keep the existing resolver fallback, so the optimization is backward-compatible with other dynamic runtimes.

## Included changes

- PR #556 — avoid redundant NeoForge build resolution and add regressions for per-Minecraft-version recommendations.

## Compatibility and upgrade notes

- No database migration is required.
- This release includes all 2.0.58 fixes, including the corrected Minecraft runtime-selector browser state handling.
- Upgrade through the canonical `cap update` flow; no manual edits under `/opt/dsm` are required.
