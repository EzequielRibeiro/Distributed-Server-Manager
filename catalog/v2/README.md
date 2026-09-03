# Execution Environment and Content Catalog

This is the single source of truth for installable game server environments and content. Execution environment manifests use the `RuntimeDefinition` schema internally and carry their version strategy, resolver configuration, artifact provider, installation target, process metadata, and platform requirements.

The published catalog currently includes Minecraft, Arma 3, Counter-Strike 2, DayZ, Mindustry, Palworld, Rust, and Team Fortress 2. Artifact acquisition supports Steam, HTTP, HTTP archives, GitHub Releases, local files, and custom providers. Additional known games may live under `games/<game>/deferred/` when their dedicated-server software exists but the current canonical installation strategy cannot yet provision it safely.

The `games/` directory contains process/runtime adapters only. It is not a second catalog. Version resolvers read configuration from the JSON environment manifest and do not load variant definitions from `games/`.

A dated Steam Top Played applicability snapshot is stored at `steam-top25-2026-09-03.json`. Popularity alone never makes a title publishable: a runtime is published only when the Agent can acquire, configure, and execute a customer-hostable dedicated server through a typed strategy.

## Layout

- `schemas/`: JSON contracts.
- `games/`: published and deferred game/runtime definitions.
- `content/`: mod, plugin, and modpack manifests.
- `providers/`: catalog and artifact-provider registry.
- `examples/`: compatibility requests.
- `support-matrix.json`: normative published/deferred runtime support state.

Instance content is activated transactionally as `content.new → content`, with the previous generation retained as `content.old`. The active root contains `mods/`, `plugins/`, `modpacks`, and `.dsm/content-lock.json`; instance metadata lives at `.dsm/instance-manifest.json`.

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
