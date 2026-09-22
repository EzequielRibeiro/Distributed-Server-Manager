# Capivara DSM 2.0.112

## Customer console history

The game console now separates live runtime output from persisted command-response history.

- Adds a collapsed **Exibir histórico de comandos** panel to Customer and Controller instance views.
- Clears persisted command-response history after a successful instance restart.
- Keeps history across start/stop.
- Improves long-line wrapping on narrow/mobile layouts.
- Preserves the current-activation journal/SSE behavior introduced in 2.0.111.

## Unified content discovery

Customer content search is provider-neutral.

- Automatically falls back between supported discovery providers such as Modrinth and CurseForge.
- Keeps provider selection out of the main search control.
- Shows provider origin, icon, author, description, content type, and download metadata on content cards.
- Keeps external file upload as a separate explicit action.

## External server query compatibility

Capivara now declares external query interoperability for every currently published Catalog v2 game.

- Adds a pinned GameDig compatibility matrix with game type, protocol, query strategy, runtime roles, and known conditional cases.
- Adds a Catalog Runtime Readiness gate for the compatibility matrix.
- Adds a Customer **Query Check** link to ismygameserver.online when the runtime has a supported public query endpoint.
- Honors the Agent public endpoint and NAT port mappings when building the external query URL.
- Uses Agent listener telemetry to show whether reserved server ports are currently listening.

Customer-visible port states are deliberately factual:

- **ONLINE** — the Agent reports a listener on the reserved socket.
- **RESERVADA** — the port is allocated but no listener is currently observed.
- **DESCONHECIDA** — Agent/network inventory is incomplete or offline.

No Steam Master Server `listed` claim is shown unless a real master-server verification is available.

## DayZ network roles

DayZ keeps a compact per-instance topology suitable for multiple managed servers:

- Game: `base + 0`
- Steam/clientPort: `base + 2`
- Steam Query: `base + 3`
- BattlEye: `base + 4`

GameDig's DayZ `+24714` value is treated as a discovery heuristic, not as the Capivara runtime allocation rule. Query Check targets the actual reserved Steam Query port directly through the Valve/A2S checker.

## Validation

- PR #770: console history lifecycle/UI.
- PR #772: unified customer content discovery.
- PR #775: external query compatibility, listener state, Query Check, DayZ port-role refinement.
- PR #775 completed the repository CI, Agent runtime, Windows parity, Catalog Runtime Readiness, P10 network/port-pool, Customer E2E, external Controller-Agent E2E, database parity, and release-readiness gates successfully.
