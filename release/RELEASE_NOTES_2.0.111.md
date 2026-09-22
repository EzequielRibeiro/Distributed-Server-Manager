# Capivara DSM 2.0.111

## Instance console current-session journal scope

The Customer Instance console now limits its initial systemd journal snapshot to the current activation of the managed game instance.

### Fixed

- Prevents logs from previous executions of the same instance from appearing in the current console.
- Prevents stale RCON diagnostics and old startup output from being mixed with the current server session.
- Uses the instance systemd `ActiveEnterTimestamp` as the lower journal boundary.
- Preserves the existing cursor-based SSE follow behavior for new live lines.

### Validation

- Current Minecraft activation timestamp resolved correctly.
- Generated journal snapshot includes the expected `--since` boundary.
- Journal cursor behavior remains intact.
- Live SSE follow remains unchanged.
- 21 targeted regression tests passed.
- PR #767 merged successfully.
