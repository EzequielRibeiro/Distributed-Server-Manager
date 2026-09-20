# Capivara DSM 2.0.94

Corrective release for live instance console updates.

## Fixes

- Fixes console views that stopped updating automatically while the SSE connection remained open but silent.
- Keeps Server-Sent Events as the primary live transport.
- Adds a liveness watchdog for Controller and Customer console surfaces.
- When no `console-line` or `console-snapshot` event arrives for 6 seconds, the UI performs a safe auxiliary console refresh every 3 seconds while the Console tab remains visible.
- Stops the safety polling when the user leaves the Console view or unloads the page.
- Preserves the existing start/restart lifecycle watchdog and normal EventSource error fallback.

## Validation

- PR #718 passed all 21 GitHub workflow gates.
- Customer runtime console live tests passed.
- Controller console watchdog tests passed.
- Console SSE backend tests passed.
- Direct Horizon validation confirmed DayZ continues writing to systemd journal and `journalctl --follow --after-cursor` works while the browser UI can become stale.
