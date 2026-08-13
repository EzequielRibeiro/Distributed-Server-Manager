# Execution Environment and Content Catalog

This is the single source of truth for installable game server environments and content. Execution environment manifests use the `RuntimeDefinition` schema internally and carry their version strategy, resolver configuration, artifact provider, installation target, process metadata, and platform requirements.

The catalog currently includes Minecraft, Arma 3, DayZ, Rust, and Mindustry. Artifact acquisition supports Steam, HTTP, HTTP archives, GitHub Releases, local files, and custom providers.

The `games/` directory contains process/runtime adapters only. It is not a second catalog. Version resolvers read configuration from the JSON environment manifest and do not load variant definitions from `games/`.

## Layout

- `schemas/`: JSON contracts.
- `runtimes/`: execution environment manifests grouped by game.
- `content/`: mod, plugin, and modpack manifests.
- `providers/`: catalog and artifact-provider registry.
- `examples/`: compatibility requests.

Instance content is activated transactionally as `content.new → content`, with the previous generation retained as `content.old`. The active root contains `mods/`, `plugins/`, `modpacks/`, and `.dsm/content-lock.json`; instance metadata lives at `.dsm/instance-manifest.json`.

## CLI

```bash
dsm catalog runtime list
dsm catalog runtime list rust
dsm catalog runtime show rust.stable
dsm catalog runtime prepare rust.stable current
dsm catalog runtime prepare mindustry.github latest
dsm content list minecraft
dsm compatibility check catalog/v2/examples/compatibility-allowed.json
```

Append `--json` when output is consumed by scripts, the Dashboard API, or another service.
