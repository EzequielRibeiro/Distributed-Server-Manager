# Database-backed audit, events, alerts and notifications

## Status

Implemented and validated on the `feat/database-audit-alerts` integration branch.

This architecture is the canonical persistence contract for operational events,
alerts and human activity in Capivara DSM. Filesystem JSON queues, historical
text logs used as databases, route-derived audit records and legacy notification
workers are not supported persistence mechanisms.

## Separation of responsibilities

Capivara maintains two independent histories.

### Human activity

Human actions are recorded semantically in `activity_audit` through
`ActivityAuditRepository`.

Examples:

- an administrator creates a customer;
- a customer changes an instance configuration;
- an operator restarts an instance;
- a controller acknowledges or resolves an alert.

The audit record stores actor, action, category, target, result, semantic
summary, timestamp, correlation information and sanitized before/after changes.
Passwords, tokens, cookies, private keys, API keys and credentials are never
persisted in audit before/after payloads.

### Operational events

Operational/domain occurrences are appended to `universal_events` through
`UniversalEventRepository`.

Examples:

- `PLACEMENT_SELECTED`;
- `PLACEMENT_UNAVAILABLE`;
- `INSTANCE_PROVISION_QUEUED`;
- `INSTANCE_PROVISION_STARTED`;
- `INSTANCE_PROVISION_COMPLETED`;
- `INSTANCE_PROVISION_FAILED`;
- `STEAM_AUTH_REQUIRED`.

`universal_events` is append-only. The operational history is not reconstructed
from dashboard routes or transient worker state files.

## Alert lifecycle

The database alert engine consumes `universal_events` using a durable cursor in
`event_consumer_cursors`.

Relevant events produce or resolve records in `alerts`, with lifecycle history
in `alert_events`.

Supported alert states are:

- `OPEN`;
- `ACKNOWLEDGED`;
- `RESOLVED`;
- `SUPPRESSED`.

Provisioning completion resolves the stable provisioning-failure and Steam
authentication alerts for the same instance topology.

The first execution of the evaluator initializes its cursor at the current end
of the event stream so enabling the new evaluator does not create alerts from
stale historical events.

## Notification delivery

`notification_outbox` is the durable boundary for external delivery and retry.
It replaces filesystem notification queues and marker files.

Delivery transports must consume database outbox rows and persist delivery
state back to the database. Dashboard alert display is read directly from the
alert repository and does not depend on the outbox.

No filesystem notification queue, `.discord_pending` marker, dashboard Discord
configuration or notification history log is part of the canonical design.

## Dashboard activity log

The Activity Log reads semantic audit records from `activity_audit`. The UI does
not infer meaning from HTTP methods or route paths.

Human-readable summaries are produced in Portuguese by the activity humanizer,
including meaningful targets and changed fields where available.

## Distributed placement and provisioning

The customer selects geography. The Controller selects the physical Agent.

Customer-facing instance creation responses expose the public instance identity,
contract and requested geographic placement only. They do not expose Agent IDs,
Node IDs or Controller filesystem paths.

The Controller persists placement, contract, network reservation and
provisioning intent in the database. It does not materialize the selected
Agent's runtime filesystem.

Provisioning retries use `instance_id` as the public/current identity. Agent,
Node, game and runtime data are resolved from database state rather than being
accepted as a filesystem identity supplied by the client.

## Persistence rules

Durable records with audit, recovery or operational-history value belong in the
configured database backend.

Transient dashboard worker snapshots may exist only for live local status where
there is no durable historical value. The dashboard state initializer therefore
does not create `alerts_state.json` or `events_state.json`.

The configured database backend remains authoritative for future recovery and
audit. No migration path in this architecture maintains a parallel old/new
persistence format.

## Retired artifacts

Repository legacy auditing prevents the return of retired event, alert and
notification services, including file-backed alert stores, notification center
workers, Discord queue/sender workers, notification timers, dashboard
notification queue files and Discord pending marker files.

## Validation

The integration is covered by the repository workflows for:

- semantic activity audit;
- Universal Event Platform;
- Universal Observability Platform;
- PostgreSQL isolated baseline deployment;
- customer workspace functional deployment;
- customer instance workspace;
- Agent instance runtime;
- Update Manager regression;
- Catalog architecture;
- release readiness;
- repository legacy audit;
- the general Linux/Windows CI matrix.

The PR is ready only after the complete workflow set is green on its final head.
