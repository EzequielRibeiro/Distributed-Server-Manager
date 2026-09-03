# P0-A — Canonical Runtime/Engine Contract

## Purpose

The canonical contract separates **what runtime the customer selected** from **what execution engine an Agent must provide**. It is intentionally independent from installation layout. Physical directories, download/extraction strategy and installer orchestration belong to P0-B Installation Strategy.

## Canonical identities

- `runtime.id` is the stable logical catalog identity, for example `minecraft.paper`, `minecraft.forge` or `dayz.stable`.
- `engine.id` is the stable execution-engine identity required by that runtime, for example `java` or `native`.
- `engine.kind` describes the execution family (`java`, `native`, `launcher`).
- Artifact providers such as Steam, HTTP or GitHub are installation/content concerns and MUST NOT be inferred as process engines. A Steam-installed DayZ server is still a native runtime process.

## Contract ownership

`runtime` owns game, edition, variant and version selection. `engine` owns platform requirements needed to execute that runtime. `launch` describes the executable/arguments relative to the resolved installation produced later by P0-B. `artifact` may carry compatibility metadata from Catalog v2, but does not select the engine.

No canonical field requires a Linux absolute path. In particular, legacy `RuntimeDefinition.installation.directory` is deliberately not copied into the canonical contract.

## Compatibility with Catalog v2

`core.runtime_engine_contract.canonical_from_runtime_v2()` is the compatibility bridge. A `RuntimeDefinition` with `schema_version: 2` is normalized as follows:

| Catalog v2 | Canonical contract |
| --- | --- |
| `id` | `runtime.id` |
| `game` | `runtime.game` |
| `edition` | `runtime.edition` |
| `variant` | `runtime.variant` |
| `version` | `runtime.version` |
| `process.engine` | `engine.id` + compatible `engine.kind` |
| `requirements.os` | `engine.requirements.os` |
| `requirements.architectures` | `engine.requirements.architectures` |
| `requirements.java` | `engine.requirements.java` |
| `process.executable/args/artifact_mode` | `launch.*` |
| `artifact` | `artifact` |
| `installation.directory` | intentionally omitted; P0-B responsibility |

The compatibility block records that the canonical form came from `RuntimeDefinition` schema v2. Existing v2 catalog entries therefore remain readable during the migration; P0-A does not require rewriting every game manifest.

## Agent validation

Both Controller/Catalog and Agent code can validate the same canonical object through `validate_runtime_engine_contract()`. `supports_agent()` performs the minimum platform compatibility check using the engine's OS and architecture requirements. Placement capabilities beyond these structural requirements are handled by later P0-C/P0-D stages.

## Boundaries

P0-A does **not** define installation directories, extraction paths, SteamCMD invocation, package caching, managed configuration precedence, resource policy or placement scoring. Those remain explicit later stages rather than leaking back into the Runtime/Engine contract.
