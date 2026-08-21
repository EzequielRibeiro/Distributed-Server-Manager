# E2 — High Availability & Disaster Recovery

## Goal

Make the Capivara control plane survive Controller failure and support tested disaster recovery without compromising the local authority model established by E1 Multi-Datacenter Federation.

E2 treats HA and DR as related but distinct concerns:

- **HA** keeps control-plane service available during a Controller failure.
- **DR** restores durable state after loss or corruption of a Controller/datacenter.

Game runtime remains owned by the Agent/datacenter. A temporary Controller outage must not become a reason to terminate healthy game instances.

## Initial architecture

An HA cluster groups Controllers into `primary`, `standby` and optional `witness` members. The cluster stores explicit RPO, RTO, quorum and failover mode (`manual` or `automatic`).

Only a healthy/degraded standby may be selected for promotion. Automatic promotion additionally requires quorum and an HA cluster configured for automatic failover.

## Split-brain prevention

Every failover request increments a persistent `fencing_epoch`. A promotion is valid only for the newest epoch. Later E2 transport/execution stages must propagate the epoch to lease holders and reject stale primaries.

The first E2 invariant is therefore:

> no promotion without quorum + candidate eligibility + a new fencing epoch.

This is intentionally fail-closed. Availability must never be obtained by allowing two Controllers to believe they are primary simultaneously.

## Recovery points

DR recovery points are immutable records describing recoverable control-plane assets. Initial kinds are:

- `database`
- `configuration`
- `control_plane`

A recovery point records source Controller, location, checksum, metadata and validation state. E2 will later connect this registry to Smart Backup, restore verification and scheduled DR drills.

## Failover state machine

`requested → validating → fencing → promoting → converging → completed`

Failures terminate in `failed` or `rolled_back`. State transitions are persisted for auditability and future Universal Event emission.

## Relationship to E1

E1 answers **where control authority exists across datacenters**. E2 answers **how that authority remains available and recoverable when a Controller or site fails**.

E2 does not replicate Agent operational databases globally and does not place the Global Controller in the game runtime execution path.

## Planned E2 increments

1. HA/DR contracts, schema, repository and CLI.
2. Controller lease/heartbeat and fencing enforcement.
3. Replication readiness and recovery-point validation.
4. Automated failure detection with hold-down and anti-flapping policy.
5. Safe failover orchestration and federation leadership convergence.
6. Failback with stale-primary fencing and data divergence checks.
7. Smart Backup integration and restore drills.
8. Admin API/dashboard surfaces and Universal Events.
9. Multi-node/WAN-loss/split-brain end-to-end tests.
10. Final E2 production gate and operational runbook.

## Completion gate

E2 is complete only when a simulated primary Controller loss can be detected, fenced, failed over and later failed back without split-brain; durable control-plane state can be restored within declared RPO/RTO; local Agents continue reconciling during control-plane interruption; and the scenario is reproducible in CI without touching an active `/opt/dsm` installation.
