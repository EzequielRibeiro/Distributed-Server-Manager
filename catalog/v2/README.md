# Execution Environment and Content Catalog

This is the single source of truth for installable game server environments and content. Execution environment manifests use the `RuntimeDefinition` schema internally and carry their version strategy, resolver configuration, artifact provider, installation target, process metadata, network requirements, and platform requirements.

The catalog currently includes Minecraft, Arma 3, DayZ, Rust, Mindustry, and Luanti. Artifact acquisition supports Steam, HTTP, HTTP archives, GitHub Releases, local files, and custom providers.

The top-level repository directory `games/` contains process/runtime adapters only. It is not a second catalog. Version resolvers read configuration from JSON environment manifests and do not load variant definitions from operational adapters.

## Layout

- `games/<game>/runtimes/`: canonical execution environment manifests grouped by game.
- `content/`: content manifests; its per-game migration is independent from the RuntimeDefinition migration.
- `providers/`: catalog and artifact-provider registry.
- `schemas/`: JSON contracts.
- `examples/`: compatibility requests.

All RuntimeDefinitions shipped by the repository now use:

```text
catalog/v2/games/<game>/runtimes/<variant>.json
```

The previous repository tree:

```text
catalog/v2/runtimes/<game>/<variant>.json
```

has been removed after migration of Arma 3, DayZ, Luanti, Mindustry, Minecraft and Rust.

`installer/catalog_paths.sh` intentionally keeps read compatibility with a legacy `runtimes/` tree when an external, older or temporary catalog root is supplied. This fallback is a compatibility contract, not a second source of truth. Canonical definitions always take precedence and runtime list output is de-duplicated by definition ID.

The Dashboard catalog adapter, compatibility resolver and placement requirements use the same canonical runtime resolution contract, preventing each subsystem from maintaining a private game list or path convention.

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
