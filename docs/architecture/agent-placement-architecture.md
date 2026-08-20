# Agent placement architecture

Status: Phase 1 architecture contract

Scope: Controller, Customer, Contract, Agent and geographic topology used by placement.

This document consolidates the architecture that already exists in the Capivara Distributed Server Manager and defines the normative eligibility rule that future placement implementations must follow. Phase 1 is documentation-only: it does not change runtime placement behavior, database schemas or dashboard routes.

## 1. Domain model

The Controller owns two related branches of the domain model:

```text
Controller
   |
   +-- Customer
   |      +-- Contract
   |
   +-- Agent
          +-- Agent Location
                  +-- Datacenter
                          +-- Region
```

### 1.1 Commercial branch

`Controller -> Customer -> Contract` describes who may request and consume an instance.

Current persistence mapping:

- `controllers`
- `customers.controller_id -> controllers.id`
- `service_contracts.customer_id -> customers.id`
- `instance_contracts` binds an instance to a service contract

The commercial contract remains responsible for service eligibility, game, limits and contract validity. It is not a substitute for infrastructure placement eligibility.

### 1.2 Infrastructure branch

`Controller -> Agent -> Agent Location -> Datacenter -> Region` describes where an instance may execute.

Current persistence mapping:

- `agents.controller_id -> controllers.id`
- `agent_locations.agent_id -> agents.id`
- `agent_locations.datacenter_id -> datacenters.id`
- `datacenters.region_id -> regions.id`

An Agent may exist before an `agent_locations` record exists. That is a valid registration/configuration state, but the Agent is not placement-ready while the geographic chain is incomplete.

## 2. Placement invariant

The existence of one or more Agents is not sufficient to allow placement.

An Agent may enter the placement candidate set only when every required element of the infrastructure chain exists, belongs to the expected Controller context and is operationally active.

Conceptually:

```text
Controller active
AND Agent active
AND Agent Location active
AND Datacenter active
AND Region active
= placement_ready
```

Equivalent reference predicate:

```python
def placement_ready(controller, agent, location, datacenter, region):
    return (
        controller is not None
        and controller.status == "active"
        and agent is not None
        and agent.status == "active"
        and location is not None
        and location.status == "active"
        and datacenter is not None
        and datacenter.status == "active"
        and region is not None
        and region.status == "active"
    )
```

This is a derived eligibility predicate. Phase 1 does not require a persisted `placement_ready` column.

### 2.1 Required relationship integrity

A positive result also assumes that the records form the same chain:

```text
agent.controller_id == controller.id
location.agent_id == agent.id
location.datacenter_id == datacenter.id
datacenter.region_id == region.id
```

Missing or mismatched relationships make `placement_ready = false`.

### 2.2 Topology readiness is not placement readiness

Topology state and placement eligibility are related but different concepts.

`topology_state == ready` means the Agent has a complete and active geographic chain:

```text
Agent Location active -> Datacenter active -> Region active
```

`placement_ready == true` additionally requires:

```text
Controller active + Agent active
```

Therefore an offline, disabled, pending, pairing or rejected Agent may have a `ready` topology and still be ineligible for placement.

## 3. Current implementation alignment

The current code already implements most of the infrastructure-side predicate in `database/location_repository.py`.

`LocationRepository.candidates()`:

- requires an Agent to belong to the requested `controller_id`;
- requires `a.status = 'active'`;
- requires an `agent_locations` row through an inner join;
- requires `agent_locations.status = 'active'`;
- requires `datacenters.status = 'active'`;
- requires `regions.status = 'active'`;
- orders candidates by current instance count and Agent identity.

This is consistent with the topology portion of the Phase 1 contract.

### 3.1 Identified gap: Controller state

`LocationRepository.candidates()` currently scopes candidates by `a.controller_id`, but it does not join `controllers` or require `controllers.status = 'active'`.

Consequently, the current query does not by itself satisfy the complete normative `placement_ready` predicate.

Phase 1 records this gap only. A later implementation phase must add Controller-state validation at the appropriate service/repository boundary and cover it with tests.

### 3.2 Identified gap: placement readiness is not a named contract in code

The current candidate query encodes several eligibility conditions directly in SQL. There is no explicit, reusable `placement_ready` contract exposed by the domain/service layer.

Phase 1 defines the semantics. A later phase may introduce a dedicated policy/service or query abstraction without adding further responsibilities to `dashboard/server.py`.

## 4. Relationship with Customer and Contract

A valid infrastructure destination does not by itself authorize provisioning.

Instance creation must continue to satisfy the commercial ownership and contract constraints independently of infrastructure placement. In simplified form:

```text
commercial_ready
    = valid Customer
    + valid active Contract
    + contract capacity / service constraints

placement_ready
    = active Controller
    + active Agent
    + active Agent Location
    + active Datacenter
    + active Region

provisioning eligibility
    = commercial_ready AND placement_ready
```

The exact commercial predicate remains owned by the customer/contract domain; this Phase 1 contract does not redefine contract lifecycle rules.

## 5. Architectural boundaries

Placement rules should be implemented outside the HTTP/dashboard composition layer.

Preferred responsibility split for future phases:

- repositories: persistence queries and relationship retrieval;
- placement policy/service: eligibility evaluation and candidate selection;
- dashboard/API routes: authentication, authorization, input/output composition;
- `dashboard/server.py`: composition/routing only where feasible.

This keeps placement logic reusable by the dashboard, CLI and future Controller services.

## 6. Phase 1 non-goals

This phase intentionally does not:

- change the candidate-selection query;
- add or alter database migrations;
- persist a `placement_ready` flag;
- modify Agent lifecycle behavior;
- enforce new Agent status values at database level;
- alter pairing, health checks, provisioning or scheduling;
- add placement logic to `dashboard/server.py`.

## 7. Source-of-truth references at Phase 1 start

The contract was reconciled against the repository state on 2026-08-19, including:

- `database/migrations/003_controller_agent_customer_model.sql`
- `database/migrations/004_instance_service_contracts.sql`
- `database/migrations/012_location_topology.sql`
- `database/infrastructure_repository.py`
- `database/location_repository.py`

The documentation defines the normative architecture from this point forward. If implementation and this contract diverge, the divergence must be explicit and reviewed rather than silently weakening placement eligibility.
