# Capivara DSM 2.0.42

Patch release following Capivara DSM 2.0.41 to publish the production fixes and distributed-runtime validation merged after the managed-firewall teardown release.

## Windows managed firewall lifecycle parity

- Reconcile managed Windows Firewall exposure before instance `start` and `restart`.
- Fail closed when firewall reconciliation fails instead of starting the runtime without the requested network policy.
- Persist the stopped desired/observed state before firewall teardown on `stop`.
- Reconcile instance-owned firewall rules to an empty desired rule set on normal and idempotent stop.
- Preserve compatibility for legacy Windows runtimes that do not carry `catalog_runtime_policy`.
- Keep firewall ownership isolated per instance so lifecycle changes do not modify rules belonging to another instance.

## Remote Agent port inspection is now read-only

The new Customer-to-Agent provisioning E2E exposed a SQLite lock in the real creation path. While `DashboardRepository.create_customer_instance()` held the allocation transaction, remote port inspection called `AgentRuntimeRepository.snapshot(..., refresh_health=True)`, which could open a nested write transaction.

This release changes that inspection path to consume the already-persisted Agent health/network projection with `refresh_health=False`.

- Port inspection remains fail-closed when the Agent is not online or when the network inventory is missing, incomplete or malformed.
- Heartbeat and monitoring paths remain responsible for refreshing Agent health.
- Remote inspection no longer mutates health while an instance allocation transaction is active.
- The fix removes the `database is locked` failure reproduced by the canonical Customer creation path on SQLite without changing PostgreSQL behavior.

## Distributed lifecycle validation

The post-2.0.41 test work strengthens release evidence without replacing the native firewall gate:

- native Linux/UFW and Windows/NetSecurity reconciliation is exercised on ephemeral CI hosts;
- the external Controller-Agent E2E now drives provisioning, RuntimeSpec/catalog runtime policy, exposure, start, restart, stop and teardown over the authenticated heartbeat transport;
- reserved ports and exposure propagate into RuntimeSpec;
- private exposure remains closed;
- firewall reconcile is required before start/restart;
- teardown occurs only after the stopped state is persisted;
- lifecycle operations are checked for idempotence and cross-instance isolation;
- the Final Customer Distributed E2E now proves the canonical Customer HTTP creation path reaches the production `AgentInstanceProvisioningRepository` with an Agent-deliverable `CapivaraInstanceProvisioningRequest`.

## Validation

The final heads of the included changes passed the relevant gates, including:

- CI, including Python validation, real Linux installation smoke, updater tests, Catalog v2, reproducible build, Linux/Windows Agent packages and the Phase 22 final E2E gate;
- Windows Agent Parity;
- Native Firewall E2E on Linux and Windows;
- External Controller Agent E2E;
- Final Customer Distributed E2E;
- P10 Agent Network and Port Pool;
- P0-D Structured Placement;
- PostgreSQL Baseline v2 Isolated Deployment;
- Customer Workspace Functional Deployment;
- Capivara 2.0 Release Readiness;
- supporting observability, customer and audit gates.

## Release scope

This release publishes the changes merged through:

- #423 — close the Windows managed-firewall lifecycle gap;
- #424 — add native Linux/Windows firewall reconciliation E2E;
- #425 — prove the distributed instance lifecycle over Controller-Agent transport;
- #426 — prove Customer handoff to the production Agent provisioning queue and keep remote Agent port inspection read-only.

No database migration is introduced by this patch release.
