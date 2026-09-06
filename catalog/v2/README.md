# Execution Environment and Content Catalog

This is the single source of truth for installable game server environments and content. Execution environment manifests use the `RuntimeDefinition` schema internally and carry their version strategy, resolver configuration, artifact provider, installation target, process metadata, and platform requirements.

Discovery follows `GameDefinition → Edition → Distribution/variant → RuntimeDefinition`. Game identity lives in `games/<game>/game.json`; executable contracts remain in `games/<game>/runtimes/*.json`. The runtime's existing `game` field references the GameDefinition ID. Edition and distribution nodes come from `edition` and `variant`, never from parsing runtime IDs.

## Layout

- `games/<game>/game.json`: GameDefinition v2 with stable ID and display name.
- `games/<game>/runtimes/`: published RuntimeDefinitions.
- `games/<game>/deferred/`: preserved definitions excluded from discovery.
- `schemas/`: shared JSON contracts.
- `content/`: mod, plugin, and modpack manifests.
- `providers/`: catalog and artifact-provider registry.
- `support-matrix.json`: normative support/publication inventory.

The repository-root `games/` directory holds adapters, not a second catalog.

## Hierarchical read API

`core.catalog_index.CatalogIndex(root).hierarchy()` returns a deterministic object with `games[].editions[].distributions[].runtime_definitions[]`. Distribution IDs equal existing `variant` values; leaves are runtime ID references. Multiple runtimes may share a distribution. `hierarchy(game_id)` filters by game, and `runtime(runtime_id)` returns a copy of the original RuntimeDefinition. Unknown IDs raise `KeyError`; invalid identities, duplicate runtime IDs and missing/mismatched game references fail validation.

The authenticated Dashboard endpoint `GET /api/catalog/hierarchy` exposes the same object, optionally filtered with `?game=minecraft`. Unknown games return 404. Existing flat runtime endpoints remain compatible. The CLI exposes `dsm catalog hierarchy [GAME] --json` (JSON output also by default).

This layer does not change Placement, Agents, Installation Strategy, runtime selection or IDs such as `minecraft.java.forge` and `luanti.stable`. Luanti remains published at 5.17.0 with `http-archive` acquisition and `cmake_source` installation. There are 20 published games and no deferred runtimes in this revision. No catalog/v3 is introduced.

The Catalog Hierarchy workflow validates every GameDefinition against its schema and checks every published runtime's game reference. To add a game, create its `game.json` before publishing runtimes. Display metadata does not control execution.

Instance content is activated transactionally as `content.new → content`, with the previous generation retained as `content.old`. The active root contains `mods/`, `plugins/`, `modpacks`, and `.dsm/content-lock.json`; instance metadata lives at `.dsm/instance-manifest.json`.

Native Linux games with simple lifecycle requirements can use the allowlisted `catalog-native` profile. Games needing private mutable bootstrap use dedicated profiles and typed `ExecStartPre` helpers. 7 Days to Die copies `serverconfig.xml` into private instance state before patching its port, Factorio creates a private initial save/settings file once, and Arma Reforger generates its server JSON inside private instance state. No helper executes arbitrary shell input.

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
