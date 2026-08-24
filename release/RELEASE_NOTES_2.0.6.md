# Capivara DSM 2.0.6

## Distributed instance lifecycle

- Fixes the standalone Controller instance lifecycle bridge so it can import the shared `core` modules before enqueueing Agent-owned runtime commands.
- Keeps start, stop and restart routed exclusively through the assigned Agent; no local or game-specific fallback is restored.

## Linux Agent runtime

- Fixes generated systemd units so `WorkingDirectory=` is emitted as a valid absolute path instead of a quoted value rejected by systemd as `bad-setting`.
- Rejects relative or line-broken working directories during runtime materialization.
- Preserves quoting for `ExecStart=` arguments and environment values.
- Adds regression coverage for the systemd materializer and standalone lifecycle bridge.

## Test-server validation

- Addresses the real `aurora-dayz-002` failure where Start reached the remote Agent but systemd refused the generated unit with `WorkingDirectory= path is not absolute`.
- The fix applies generically to Linux Agent-managed game runtimes and is not specific to DayZ.
