# Phase 6 — Correct instance creation failure handling

Status: implemented contract.

## Goal

`POST /api/instance/create` must always return a valid HTTP response. Placement
availability is a domain condition, not a server-thread failure.

## Domain error

Placement absence is represented by `PlacementUnavailable`, defined in
`dashboard/placement_errors.py`.

The exception carries diagnostic context for trusted logs only:

- `reason`;
- `agents_evaluated`;
- `requested_region_id`.

The customer response never serializes this context.

## HTTP contract

`dashboard/instance_creation_http.py` owns the transport mapping.

When no eligible Agent can satisfy the request:

```json
{
  "error": "placement_unavailable",
  "message": "Nenhum ambiente está disponível para criar este servidor."
}
```

HTTP status: `409 Conflict`.

The boundary also catches unexpected exceptions and returns a controlled 500
response rather than allowing an exception to terminate the socket handler.

## Logging contract

A rejected placement emits an internal structured record containing:

- customer scope id;
- resolved contract id when available;
- game;
- requested region;
- internal rejection reason;
- number of Agents evaluated.

These fields are written to the application logger and therefore to the
Dashboard service journal under systemd. They are not included in the customer
response.

## Placement orchestration

`dashboard/placement_service.py` checks the eligible candidate set before
calling the scoring engine. An empty set raises `PlacementUnavailable` instead
of relying on a generic `RuntimeError` from lower-level selection code.

The rejection reason reuses the Phase 5 placement-readiness snapshot when the
entire infrastructure is unavailable. If infrastructure is otherwise ready but
a requested Region has no eligible Agent, the internal reason is
`requested_region_unavailable`.

## Runtime integration

The active Dashboard service now starts `dashboard/server_part9.py`.

`server_part9.py` layers the Phase 6 route over `server_part8.py` without adding
new behavior to the already large `dashboard/server.py`.

## Invariants

1. no absence-of-placement `RuntimeError` reaches `socketserver`;
2. no placement diagnostic details are exposed to customers;
3. placement unavailability is a 409 domain response;
4. unexpected create failures still produce a valid HTTP 500 response;
5. successful creation remains HTTP 201;
6. existing customer RBAC and instance creation implementation remain intact;
7. no direct change is made to an active `/opt/dsm` installation.
