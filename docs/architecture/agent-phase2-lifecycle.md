# Agent lifecycle and placement — Phase 2 implementation

Status: Phase 2 implementation contract

This document records the executable Agent lifecycle and placement guarantees delivered after the Phase 1 architecture/state vocabulary.

## Delivered invariants

Phase 2 makes the following behavior executable and tested:

1. New Agents are registered under an active Controller in `pending` state.
2. Agent and node identity creation is atomic; duplicate identities or an invalid Controller fail without partial registration.
3. Lifecycle changes use the official state machine in `core/agent_lifecycle.py`.
4. Lifecycle persistence reads the current state and applies the validated transition in one transaction.
5. Pairing control uses semantic actions over that same state machine:
   - `start`: `pending -> pairing`
   - `approve`: `pairing -> active`
   - `reject`: `pairing -> rejected`
   - `cancel`: `pairing -> pending`
6. Administrative re-entry from `disabled` or `rejected` returns to `pending` before activation can happen again.
7. Controller/admin RBAC is applied to registration, lifecycle inspection and lifecycle mutation. Controller users are constrained to their own Controller scope.
8. Placement candidates fail closed unless Controller, Agent, Agent Location, Datacenter and Region are all active.
9. `topology_state` and `placement_ready` are derived values and are not persisted as independent columns.
10. An Agent moving to `offline` immediately stops being a placement candidate; `offline -> active` restores lifecycle eligibility, subject to topology readiness.

## Lifecycle graph

```text
pending  -> pairing | disabled | rejected
pairing  -> pending | active | disabled | rejected
active   -> offline | disabled
offline  -> active | disabled
disabled -> pending
rejected -> pending
```

Reapplying the same state is an idempotent no-op.

## Registration and pairing flow

```text
register
  |
  v
pending
  |
  | pairing start
  v
pairing
  |\
  | \ reject
  |  v
  | rejected
  |
  | approve
  v
active
```

Registration never creates a remotely supplied Agent directly as `active`.

The historical/local bootstrap path may still create a pre-trusted bootstrap Agent as active. That bootstrap behavior is compatibility behavior and is not the remote Agent enrollment contract.

## Placement gate

The final Phase 2 placement predicate remains:

```text
Controller.status == active
AND Agent.status == active
AND Agent Location.status == active
AND Datacenter.status == active
AND Region.status == active
```

The integration tests exercise the complete sequence:

```text
pending + ready topology  -> not candidate
pairing + ready topology  -> not candidate
active + ready topology   -> candidate
offline + ready topology  -> not candidate
active + ready topology   -> candidate again
```

## Persistence ownership

- `core/placement_readiness.py`: pure topology/placement predicates.
- `core/agent_lifecycle.py`: pure lifecycle state machine.
- `database/agent_lifecycle_repository.py`: transactional lifecycle persistence.
- `database/agent_registration_repository.py`: atomic pending registration.
- `database/location_repository.py`: geographic topology and placement candidate query.
- `dashboard/infrastructure_service.py`: derived readiness exposure.
- `dashboard/agent_lifecycle_api.py`: RBAC-aware administration/enrollment surface.

No lifecycle feature is implemented in `dashboard/server.py`.

## Phase 2 completion boundary

Phase 2 establishes the Controller-side domain, persistence and authorization contracts required for Agent enrollment and placement.

The following are deliberately outside Phase 2 and belong to the secure Agent transport/health work that follows:

- cryptographic enrollment tokens or certificates;
- network handshake protocol between remote Agent and Controller;
- heartbeat transport and timeout policy that automatically drives `active <-> offline`;
- key rotation and Agent credential revocation;
- reconnect/reconciliation protocol for running instances;
- UI controls for the complete pairing experience;
- database-level CHECK/trigger parity for lifecycle values across SQLite, MySQL and PostgreSQL.

Those mechanisms must call the Phase 2 lifecycle and placement contracts rather than define competing state rules.
