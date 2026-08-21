# E1 — Multi-Datacenter Federation

## Goal

Federate multiple Capivara Controllers without turning the global control plane into the runtime owner of every Agent. Each datacenter remains authoritative for its local Agents and instances and continues operating during temporary WAN/control-plane loss.

## Authority model

- Global Controller: global inventory projection, routing policy and cross-datacenter intent.
- Datacenter Controller: authoritative local topology, Agents, instance desired state and local execution.
- Agent: authoritative operational execution and local reconciliation.

Federation does **not** copy Agent operational databases between datacenters.

## Federation snapshot

Controllers exchange a bounded projection containing only non-secret inventory data: regions, datacenters, Agent health/capabilities, instance placement/state and aggregate capacity. Snapshots are versioned, sequenced and checksum protected. Receiver identity validation fails closed.

## Routing

Explicit routes may target region, datacenter, customer, game or global scopes. Only online/degraded Controllers are eligible. Datacenter and region routes are resolved deterministically by route priority and Controller priority.

## Failure behavior

A WAN partition must not stop local game instances. Local Controller/Agent reconciliation continues. Global inventory becomes stale and the remote Controller is marked degraded/offline; cross-datacenter placement must not target an unreachable Controller. When connectivity returns, a newer sequenced snapshot converges the global projection.

## Security boundaries

Federation endpoints require HTTPS. Federation payloads contain no enrollment tokens, API tokens, passwords, RCON credentials or arbitrary shell commands. Future transport authentication must use Controller identities with rotation/revocation and replay protection.

## Persistence

Migration `039_multidatacenter_federation.sql` adds controller registry, immutable received snapshots and routing policy with equivalent schemas for SQLite, PostgreSQL and MySQL/MariaDB.

## Completion gate

E1 is complete when Controller identity/authentication, snapshot persistence, global inventory, routing/placement handoff, event federation, WAN partition recovery, administrative CLI/API and CI end-to-end tests are integrated without weakening local datacenter autonomy.
