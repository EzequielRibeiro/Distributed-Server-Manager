# P0-B — Canonical Installation Strategy

P0-B separates installation from both logical runtime identity and execution engine identity established in P0-A.

## Ownership

- `runtime_id`: logical catalog identity.
- `engine_id`: execution identity required to start the server process.
- `acquisition.provider`: where the runtime artifact comes from.
- `installer.method`: which installer executor the Agent uses to materialize the artifact.
- `layout`: semantic paths relative to the instance root.
- Agent platform: resolves semantic layout to absolute Linux/Windows paths.

`steam` is therefore an acquisition provider and `steamcmd` is an installation method. Neither one changes a native runtime into a different execution engine.

## Canonical rule

Catalog contracts MUST NOT require absolute installation paths. `layout.working_dir` and `layout.artifact_target` are relative and traversal-safe. Absolute paths exist only after the selected Agent supplies its local `instance_root`.

Examples:

- Linux root `/srv/capivara/instances/i-1` + `server` -> `/srv/capivara/instances/i-1/server`.
- Windows root `C:\Capivara\instances\i-1` + `server` -> `C:\Capivara\instances\i-1\server`.

## Provider → installer mapping

- `steam` → `steamcmd`
- `http`, `http-archive`, `github` → `download`
- `local` → `copy`
- `source-build` → `source-build`
- `custom` → `custom`

This mapping is installation policy, not process-engine policy.

## RuntimeDefinition v2 compatibility

The P0-A normalizer intentionally drops `installation.directory`. P0-B derives its strategy from the normalized Runtime/Engine contract and uses only relative semantic layout. Legacy absolute directories may remain in v2 manifests for compatibility readers, but they are not canonical semantics.

## Separation from InstallationPlan

`catalog/v2/schemas/installation-plan.schema.json` describes content operations such as mods/plugins/modpacks. `InstallationStrategy` describes how the runtime itself is acquired and materialized. These contracts remain separate.
