# Capivara DSM 2.0.113

## Unified game console

The instance console keeps one visual stream for operators and customers.

- Removes the separate **Exibir histórico de comandos** panel from Customer and Controller instance pages.
- Keeps native game-server output and commands echoed by the game server together in the main terminal.
- Preserves persisted command-history data internally without rendering it as a duplicate console surface.
- Keeps restart-time command-history cleanup behavior introduced previously.

## Read-only update CLI

Read-only update commands no longer require access to private DSM runtime configuration.

- `cap update check` and `cap update history` run without sourcing `/opt/dsm/config/dsm.conf`.
- Private `dsm.conf` permissions remain restricted.
- Role enforcement is preserved through the read-only local-role resolver.
- `cap update preflight` and `cap update run` remain on the privileged/full-bootstrap path.
- Update history is kept readable for normal shell users.

## Validation

- PR #777: single game-console surface.
- PR #778: config-free read-only update commands with preserved role enforcement.
- PR #778 completed CLI Unification, Update Manager Regression, Agent Local CLI, release-readiness, distributed E2E, and repository CI successfully.
