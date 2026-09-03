# Execution Environment and Content Catalog

This is the single source of truth for installable game server environments and content. Execution environment manifests use the `RuntimeDefinition` schema internally and carry their version strategy, resolver configuration, artifact provider, installation target, process metadata, and platform requirements.

The published catalog currently includes Minecraft, Arma 3, Arma Reforger, Counter-Strike 2, DayZ, Factorio, Garry's Mod, Left 4 Dead 2, Mindustry, Palworld, Project Zomboid, Rust, Satisfactory, 7 Days to Die, and Team Fortress 2. Artifact acquisition supports Steam, HTTP, HTTP archives, GitHub Releases, local files, and custom providers. Additional known games may live under `games/<game>/deferred/` when their dedicated-server software exists but the current canonical installation strategy cannot yet provision it safely.

The current deferred set includes FiveM, Valheim, ARK: Survival Ascended, The Isle Evrima, and Luanti. Deferred definitions are deliberately not customer-selectable. FiveM, Valheim, and The Isle require credential handling that must not leak into RuntimeSpec, systemd argv/environment, provisioning JSON, or logs. ARK: Survival Ascended currently needs a Windows-native or typed Wine/Proton execution path that the Linux Agent does not provide.

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
