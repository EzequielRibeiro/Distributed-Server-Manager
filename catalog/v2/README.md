# Execution Environment and Content Catalog

This is the single source of truth for installable game server environments and content. Execution environment manifests use the `RuntimeDefinition` schema internally and carry their version strategy, resolver configuration, artifact provider, installation target, process metadata, and platform requirements.

The catalog currently identifies Arma 3, DayZ, Luanti, Mindustry, Minecraft, and Rust. Artifact acquisition supports Steam, HTTP, HTTP archives, GitHub Releases, local files, and custom providers.

The top-level `games/` directory contains process/runtime adapters only. It is not a second catalog. Version resolvers read configuration from the catalog manifests and do not load installable variant definitions from `games/`.

## Layout

- `games/`: canonical namespace being introduced for declarative data grouped by game;
- `runtimes/`: current execution environment manifests grouped by game; retained during migration;
- `content/`: current mod, plugin, and modpack manifests; retained during migration;
- `providers/`: reusable catalog and artifact-provider registry;
- `schemas/`: shared JSON contracts;
- `examples/`: compatibility requests.

The reorganization toward `catalog/v2/games/<game>/` is incremental. Existing runtime and content paths remain authoritative for the current APIs until compatibility loaders and migration tests are in place. See `docs/architecture/game-directory-layout.md`.

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
