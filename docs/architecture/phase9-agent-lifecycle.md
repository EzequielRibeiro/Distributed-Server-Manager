# Phase 9 — Agent Lifecycle and heartbeat

## Goal

Make Agents first-class multi-host resources while keeping administrative
lifecycle separate from operational connectivity.

## Lifecycle states

The supported persisted lifecycle vocabulary is:

- `discovered`
- `pending`
- `pairing`
- `active`
- `offline` (legacy/manual lifecycle compatibility)
- `disabled`
- `rejected`

New discovery may start at `discovered`. Explicit Phase 2 registration remains
`pending` for compatibility.

`offline` remains accepted in `agents.status`, but heartbeat processing never
writes it. A healthy administrative Agent therefore normally remains
`status=active` while connectivity is represented independently.

## Operational health

Heartbeat health is stored in `agent_runtime_inventory.health_status`:

- `online`: heartbeat age below degraded threshold
- `degraded`: heartbeat age between degraded and offline thresholds
- `offline`: no heartbeat or heartbeat age beyond offline threshold

Defaults:

- heartbeat interval: 30 seconds
- degraded after: 60 seconds
- offline after: 120 seconds

This separation allows combinations such as:

- `active / online`
- `active / degraded`
- `active / offline`
- `disabled / online`

The last combination is intentionally possible: receiving packets from a
machine must never override an administrator disabling it.

## Runtime inventory

The Controller can retain at least:

- agent_id
- node_id
- controller_id
- hostname
- operating system
- architecture
- Capivara version
- network address
- fingerprint
- capabilities
- CPU
- RAM
- storage
- managed port ranges
- lifecycle status
- health status
- last_seen

Port ranges continue to use `agent_port_ranges`; they are included in the
aggregated Agent runtime snapshot rather than duplicated.

## Heartbeat boundary

`dashboard/agent_heartbeat_api.py` is transport-neutral. It requires an
`authenticated_agent_id` supplied by the future secure Agent transport and
rejects a payload that claims another Agent identity. It deliberately does not
create an unauthenticated public heartbeat endpoint.

## Placement

Existing Agents without a runtime telemetry row retain legacy compatibility.
Once an Agent begins heartbeat reporting, only `health_status=online` may
receive new instance placement. `degraded` and `offline` Agents keep existing
instances but are excluded from new allocations.

Placement readiness counts use the same rule so Dashboard readiness and actual
placement do not disagree.

## Security boundary

Fingerprint is inventory/trust material, not yet a complete credential
mechanism. Certificate/token enrollment, rotation and revocation remain the
responsibility of the secure Controller↔Agent transport phase.
