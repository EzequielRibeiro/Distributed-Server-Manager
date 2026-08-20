# Agent and topology state contracts

Status: Phase 1 normative state contract

This document defines the official Agent lifecycle states and the derived topology states used by Capivara DSM. It records the vocabulary that future pairing, health, placement and dashboard code must share.

Phase 1 does not change runtime state transitions or database constraints.

## 1. Official Agent states

The only official Agent lifecycle states are:

```text
pending
pairing
active
offline
disabled
rejected
```

### `pending`

The Agent is known to the Controller but has not completed the process required to become operational.

Placement eligibility: **no**.

Typical meaning: newly registered, awaiting pairing/approval or other activation prerequisites.

### `pairing`

The Agent is in the process of establishing its trusted relationship with the Controller.

Placement eligibility: **no**.

This state must not be interpreted as active merely because the Agent can communicate during the pairing exchange.

### `active`

The Agent has completed the required lifecycle activation and is considered operational at the Agent-state level.

Placement eligibility: **conditional**.

`active` alone does not imply `placement_ready`. The complete topology and Controller must also satisfy the placement contract.

### `offline`

The Agent is registered/accepted but is currently considered unavailable because connectivity or health requirements are not satisfied.

Placement eligibility: **no**.

Existing instances may require separate recovery/reconciliation behavior; that behavior is outside Phase 1.

### `disabled`

The Agent has been administratively disabled.

Placement eligibility: **no**.

Administrative disablement takes precedence over otherwise healthy connectivity or a complete topology.

### `rejected`

The Agent registration or pairing attempt was explicitly rejected and the Agent must not become an execution target unless a later administrative flow changes its lifecycle state.

Placement eligibility: **no**.

## 2. State-set invariant

Future code that creates, mutates, validates or serializes Agent lifecycle state must use the official set:

```python
AGENT_STATES = {
    "pending",
    "pairing",
    "active",
    "offline",
    "disabled",
    "rejected",
}
```

Phase 1 records this contract but does not yet add a database `CHECK`, enum, migration or transition engine.

### Current implementation note

The existing `agents.status` column was introduced with `DEFAULT 'pending'`, but without a database-level constraint limiting values to this official set. This is an implementation gap to be handled in a later phase with migration parity across supported database backends.

## 3. Official topology states

Topology state is derived from the Agent's geographic placement chain. The official values are:

```text
unconfigured
partial
ready
```

Topology state is not the same as Agent lifecycle state.

### `unconfigured`

No usable Agent Location has been configured for the Agent.

Canonical condition:

```text
Agent exists
AND Agent Location does not exist
```

This state is expected during registration, migration and initial Agent setup.

Placement eligibility: **no**.

### `partial`

At least part of the geographic topology has been configured, but the complete active chain is not valid.

Examples include:

- Agent Location exists but its Datacenter cannot be resolved;
- Datacenter exists but its Region cannot be resolved;
- Agent Location is disabled;
- Datacenter is disabled;
- Region is disabled;
- relationship identifiers do not form one consistent chain.

Placement eligibility: **no**.

`partial` is intentionally broader than “missing record”: it also covers a configured chain that is structurally present but not active end-to-end.

### `ready`

The complete geographic topology exists, relationships are consistent and every topology component is active:

```text
Agent Location active
AND Datacenter active
AND Region active
```

Placement eligibility: **conditional**.

A `ready` topology still requires an active Controller and an Agent whose lifecycle state is `active`.

## 4. Reference topology derivation

Conceptually:

```python
def topology_state(location, datacenter, region):
    if location is None:
        return "unconfigured"

    complete = (
        datacenter is not None
        and region is not None
        and location.datacenter_id == datacenter.id
        and datacenter.region_id == region.id
    )

    if not complete:
        return "partial"

    active = (
        location.status == "active"
        and datacenter.status == "active"
        and region.status == "active"
    )

    return "ready" if active else "partial"
```

This reference describes semantics; it is not a requirement to use this exact function shape.

## 5. `placement_ready` contract

`placement_ready` is true only when both lifecycle and topology requirements pass in the same Controller context.

Reference expression:

```text
placement_ready =
    Controller.status == active
    AND Agent.status == active
    AND topology_state == ready
```

Expanded:

```text
Controller active
AND Agent active
AND Agent Location active
AND Datacenter active
AND Region active
= placement_ready
```

All other combinations produce `placement_ready = false`.

## 6. Minimum truth table

| Controller | Agent | Topology | placement_ready |
|---|---|---|---|
| active | active | ready | true |
| active | active | partial | false |
| active | active | unconfigured | false |
| active | pending | ready | false |
| active | pairing | ready | false |
| active | offline | ready | false |
| active | disabled | ready | false |
| active | rejected | ready | false |
| not active | active | ready | false |

The table is normative. Candidate-selection implementations may apply additional constraints, but they must never treat any row marked `false` as placement-ready.

## 7. Persistence and API guidance for later phases

When implementation begins, the following principles apply:

- Agent lifecycle state is persistent domain state.
- Topology state should normally be derived from persisted relationships/status rather than stored as a second source of truth.
- `placement_ready` should normally be derived from Controller, Agent and topology state rather than persisted.
- API/dashboard labels must use these exact official state names internally, even if localized display text is used for users.
- Unknown Agent lifecycle values must not be treated as active or placement-ready.
- Missing topology data must fail closed: no placement candidate is produced.

## 8. Phase boundary

Transition rules such as `pending -> pairing -> active`, heartbeat thresholds for `offline`, reactivation rules and rejection recovery are intentionally not standardized in Phase 1. They require the pairing/health architecture and tests that belong to subsequent work.

The Phase 1 guarantee is narrower and mandatory: a shared vocabulary exists, placement fails closed, and `active Agent` is necessary but not sufficient for placement.
