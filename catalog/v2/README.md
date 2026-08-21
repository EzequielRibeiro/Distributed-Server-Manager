# Execution Environment and Content Catalog

This is the single source of truth for installable game server environments and content. Execution environment manifests use the `RuntimeDefinition` schema internally and carry their version strategy, resolver configuration, artifact provider, installation target, process metadata, and platform requirements.

The catalog currently includes Minecraft, Arma 3, DayZ, Rust, Mindustry, and Luanti. Artifact acquisition supports Steam, HTTP, HTTP archives, GitHub Releases, local files, and custom providers.

The top-level `games/` directory contains process/runtime adapters only. It is not a second catalog. Version resolvers read configuration from JSON environment manifests and do not load variant definitions from `games/`.

## Layout

- `games/`: canonical per-game namespace being introduced incrementally.
- `runtimes/`: legacy-compatible execution environment manifests grouped by game during migration.
- `content/`: legacy-compatible mod, plugin, and modpack manifests during migration.
- `providers/`: catalog and artifact-provider registry.
- `schemas/`: JSON contracts.
- `examples/`: compatibility requests.

The target runtime path is:

```text
catalog/v2/games/<game>/runtimes/<variant>.json
```

During migration, the current path remains supported:

```text
catalog/v2/runtimes/<game>/<variant>.json
```

`installer/catalog_paths.sh` resolves both layouts. Canonical definitions are preferred when the same runtime ID exists in both locations, while legacy-only definitions remain visible. Runtime list output is de-duplicated by definition ID.

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
