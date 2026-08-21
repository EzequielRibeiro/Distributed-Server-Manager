# E1 — Multi-Datacenter Federation

## Objective

Federate Capivara Controllers without turning the global control plane into the execution path for game instances. Each datacenter remains authoritative for its local Agents and operational runtime; federation exports inventory, capacity and policy metadata upward.

## Authority model

- Global Controller: global inventory, cross-region policy, external API aggregation and placement intent.
- Regional/Datacenter Controller: authoritative local topology, Agents, instances and runtime operations.
- Agent: authoritative observed operational state and reconciliation for its instances.

A remote Controller must never mutate another datacenter's database directly. Cross-datacenter actions are structured requests against authenticated federation capabilities.

## Federation identity

Members have a stable `controller_id`, role (`global`, `regional`, `datacenter`), optional Region/Datacenter binding, HTTPS endpoint, state and a separately rotated federation credential. Only the credential hash is persisted.

## Inventory

Datacenter Controllers publish immutable snapshots containing a bounded projection of Agents, instances and aggregate capacity. Snapshots are idempotent and controller-scoped. The global inventory is a projection, not a replacement for local operational state.

## Placement

Policy modes:

- `local_first`: keep workload in the requested/current datacenter when eligible.
- `region_first`: search eligible datacenters in the requested region before fallback.
- `global`: allow any eligible federated datacenter.

`cross_region_fallback` is explicit and defaults to false. Existing local placement rules (health, capabilities, ports and runtime requirements) remain mandatory after a datacenter is selected.

## Failure semantics

Loss of federation connectivity marks remote inventory stale/degraded but does not stop local Agents or instances. A disconnected datacenter continues reconciling its own runtime. Global placement must not select a stale/offline member for new workloads.

## Events

C1 Universal Events remain locally durable. Federation uses per-controller cursors for at-least-once forwarding and idempotent ingestion. Event identity is preserved across datacenters.

## Security boundaries

- HTTPS is mandatory for remote federation endpoints.
- No arbitrary shell/SQL is transported.
- No direct remote database access.
- Credentials are scoped to federation and rotatable independently of Agent credentials and external API tokens.
- Customer/RBAC checks remain enforced by the authoritative Controller before local execution.

## Persistence

Migration 039 adds `federation_members`, `federation_inventory_snapshots`, `federation_policies` and `federation_event_cursors` with SQLite, PostgreSQL and MySQL/MariaDB parity.
