# Capivara DSM 2.0.26

Patch release for the public `cap` CLI bootstrap handoff.

## Fixed

- `cap config show` no longer fails with `config_show: command not found`.
- `DSM_BOOTSTRAP_LOADED` is kept local to each shell process instead of being exported across the `cap -> dsm-compat` exec boundary.
- Exec'd compatibility children now initialize their own bootstrap and load `core/config.sh` correctly.
- Added regression coverage for the exact `cap config show` handoff.

## Compatibility

- No database schema changes relative to 2.0.25.
- No catalog/runtime contract changes.
- No Agent package behavior changes are required by this fix.
