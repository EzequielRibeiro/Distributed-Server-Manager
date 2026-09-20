# Capivara DSM 2.0.100

Network-port ownership hardening release for multi-game provisioning.

## Fixes

- Reserves four explicit Minecraft Java service roles as one logical block: game TCP, RCON TCP, Query UDP and Votifier TCP.
- Materializes the reserved Minecraft Query port into `server.properties` instead of leaving the default `25565`, preventing latent Query collisions when the feature is enabled.
- Reserves a dedicated Votifier TCP port without inventing plugin-specific configuration; the runtime receives the canonical `PORT_VOTIFIER` value for plugin integration.
- Changes inter-instance allocation from protocol-scoped reuse to node-wide numeric port ownership: a number owned by one instance on UDP is no longer available to another instance on TCP, and vice versa.
- Preserves legitimate same-instance dual-protocol bindings when a runtime explicitly requires TCP and UDP on the same numeric port.
- Inspects both TCP and UDP occupancy during provisioning and serializes PostgreSQL/MySQL allocations with Agent and node locks plus a final `(node_id, port)` ownership check before persistence.
- Detects legacy cross-protocol reservation collisions during runtime reconciliation and safely relocates offline port blocks while refusing silent relocation of running instances or listening legacy ports.

## Validation

- PR #730 passed all 44 workflows, including CI, Minecraft Java Runtime, Catalog Runtime Readiness and M10 Final E2E Release Validation.
- PR #731 passed all 16 triggered workflows, including CI, PostgreSQL/MySQL/MariaDB isolated deployment, P10 Agent Network and Port Pool, Final Customer Distributed E2E and Release Readiness.
- Focused allocator and reconciliation tests confirm the prior DayZ `24000/UDP` versus Minecraft `24000/TCP` case is detected and the Minecraft block is reassigned to `24004-24007`.
- Before release preparation, `main` had no open pull requests and no remote branches containing commits not merged into `main`.
