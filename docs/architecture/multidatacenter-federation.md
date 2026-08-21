# E1 — Multi-Datacenter Federation

## Goal

Federate multiple Capivara Controllers without turning the global control plane into the runtime owner of every Agent. Each datacenter remains authoritative for its local Agents and instances and continues operating during temporary WAN/control-plane loss.

## Authority model

```text
Global Controller
      |
      +-- Regional / Datacenter Controller
                    |
                    +-- Agent
                           |
                           +-- Instances
```

- Global Controller: global inventory projection, routing policy and cross-datacenter intent.
- Regional/Datacenter Controller: authoritative local topology, Agents, instance desired state and local placement.
- Agent: authoritative operational execution and local reconciliation.

Federation does **not** copy Agent operational databases or transfer instance ownership implicitly.

## Controller authentication

Controller-to-Controller traffic uses a federation credential distinct from Dashboard sessions, D2 API tokens and Agent enrollment credentials. The credential is presented once; only a SHA-256 verifier is persisted. Credentials can expire and be revoked.

Every peer request additionally carries a timestamp and nonce. Requests outside the configured clock-skew window fail closed and `(controller_id, nonce)` is claimed atomically, so replayed requests are rejected. Federation endpoints require HTTPS.

## Inventory and health

Controllers exchange a bounded projection containing only non-secret inventory data: regions, datacenters, Agent health/capabilities, instance placement/state and aggregate capacity. Snapshots have schema version, Controller identity, monotonic sequence, timestamp and SHA-256 checksum.

The receiver rejects identity mismatch, checksum mismatch, stale sequence and conflicting replay. An identical sequence/checksum is idempotent. `last_seen_at` drives online/degraded/offline health without modifying local runtime ownership.

## Global inventory

The Global Controller aggregates the latest valid snapshot from each peer into a read model. Keys remain namespaced by originating Controller, preventing accidental collisions and preserving authority boundaries. Capacity is aggregated only from numeric metadata.

## Routing and placement handoff

Routing supports `local_first`, `region_first` and `global`, plus explicit customer, game, datacenter, region and global routes. Disabled/offline Controllers are never selected. Cross-region fallback must be explicitly enabled.

A global placement decision produces a structured, checksummed handoff. The target Datacenter Controller still runs its normal local placement pipeline and chooses an eligible Agent. Handoffs use a stable `request_id`, making repeated requests idempotent.

```text
Global placement
      |
      v
Controller selection
      |
      v
Placement handoff
      |
      v
Datacenter Controller
      |
      v
Local placement -> Agent -> Instance
```

## Event federation

C1 Universal Events may be forwarded in bounded batches. Batches are sequenced and checksummed. The receiver stores per-Controller event receipts and a cursor; duplicate event IDs with identical checksums are idempotent, while conflicting replays fail closed. The original C1 `event_id` remains the global deduplication identity.

## WAN partitions

A WAN partition must not stop local game instances. Local Controller/Agent reconciliation, lifecycle, backup and other local capabilities continue. Global inventory becomes stale and peer health moves to degraded/offline; new cross-datacenter placement does not target an unavailable Controller. On reconnection a newer snapshot and event cursor converge global state without reassignment of existing instances.

## Administrative surfaces

CLI:

```text
cap federation status
cap federation members
cap federation inventory
cap federation peer-add ...
cap federation peer-disable ...
cap federation credential-issue ...
cap federation credential-revoke ...
cap federation policy-show
cap federation policy-set ...
cap federation handoff-create ...
```

Dashboard/admin API uses `GET/POST /api/federation`. Controller peer ingestion uses dedicated `/api/federation/v1/snapshot` and `/api/federation/v1/events` endpoints with federation authentication.

## Security boundaries

Federation metadata rejects token/password/secret/credential fields recursively and does not carry enrollment credentials, API tokens, RCON credentials, shell commands or scripts. Federation is metadata and structured intent only. Controller credentials are independent, revocable and replay protected.

## Persistence

Migration `039_multidatacenter_federation.sql` is active in the standard migration directories for SQLite, PostgreSQL and MySQL/MariaDB. It persists Controller registry, federation credentials, request nonces, snapshots, routes, event cursors/receipts and placement handoffs.

## Completion gate

E1 is complete when the dedicated federation workflow proves contract compilation, repository behavior, authentication/replay protection, snapshot sequence safety, global aggregation, routing/handoff idempotency, event deduplication and active migration parity, while the repository-wide CI remains green.
