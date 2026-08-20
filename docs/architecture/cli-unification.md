# CLI Unification — `cap` as the official command

## Status

Phase 1 — compatibility routing.

## Decision

`cap` becomes the official Capivara DSM command-line interface.

`dsm` remains temporarily available for backward compatibility while command groups are migrated incrementally.

The project must avoid implementing new user-facing command groups only in `dsm`.

## Phase 1

The first unification phase does not duplicate existing operational logic.

`cap` owns the new distributed-management commands directly, including:

```text
cap infrastructure ...
cap agent deploy ...
```

Existing stable operational groups are exposed through `cap` by delegating to the existing `bin/dsm` implementation:

```text
cap server ...
cap doctor ...
cap monitor ...
cap mods ...
cap backup ...
cap user ...
cap runtime ...
cap config ...
cap steam ...
cap game ...
cap catalog ...
cap content ...
cap compatibility ...
cap update ...
cap database ...
cap instance ...
cap operations ...
cap agent ports ...
```

Short compatibility forms are also preserved:

```text
cap start ...
cap stop ...
cap restart ...
cap status ...
```

## Routing rule

Native `cap` commands always take precedence over compatibility routing.

For example:

```text
cap agent deploy
```

is executed by the native Agent deployment implementation, while:

```text
cap agent ports
```

is delegated to the existing `dsm agent ports` implementation during Phase 1.

This prevents duplicate implementations and makes the transition reversible.

## Migration phases

### Phase 1 — entry-point unification

- expose legacy operational groups through `cap`;
- retain `dsm` behavior unchanged;
- add routing contract tests;
- declare `cap` the official CLI in new documentation.

### Phase 2 — extract command modules

Move command implementations out of the large `bin/dsm` dispatcher into dedicated modules/scripts where practical.

Both CLIs may call those modules during the transition.

### Phase 3 — make `cap` the real dispatcher

`cap` calls the extracted implementations directly rather than delegating to `bin/dsm`.

No user-facing behavior should change solely because of this migration.

### Phase 4 — invert compatibility

After all supported groups are native in `cap`, `bin/dsm` becomes a thin compatibility wrapper that forwards its arguments to `cap`.

Conceptually:

```bash
exec cap "$@"
```

A deprecation notice may be added, provided it does not break machine-readable output.

### Phase 5 — retirement decision

Keep `dsm` compatibility for multiple releases before considering removal.

Removal requires a dedicated compatibility review covering scripts, documentation, installer behavior, systemd units and operator workflows.

## Role-aware future CLI

The unified CLI must support role-aware command availability:

- Controller: administrative/orchestration commands;
- Agent: local Agent diagnostics and resources;
- Hybrid: both command sets.

This is especially important before adding the planned Agent-local commands such as:

```text
cap agent status
cap agent doctor
cap agent capabilities
cap agent network
cap agent game-data ...
```

## Compatibility requirement

During migration, a command that already works through `dsm` must not silently change semantics when invoked through `cap`.

Arguments and exit codes should be preserved by delegation unless a command is explicitly migrated and covered by tests.

## Non-goals of Phase 1

Phase 1 does not:

- remove `dsm`;
- rewrite the existing operational modules;
- change the active installation automatically;
- add new release/version numbers;
- alter command semantics;
- migrate systemd units to invoke `cap`.

## Test contract

`tests/cli_unification_test.sh` verifies that:

- representative operational commands delegate through `cap` with arguments intact;
- `cap agent ports` follows the compatibility path;
- `cap agent deploy` remains native;
- help output identifies `cap` as the CLI being consolidated.

A dedicated `CLI Unification` GitHub Actions workflow runs this contract on relevant changes.
