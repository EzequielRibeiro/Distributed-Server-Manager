# Capivara DSM 2.0.79

Release consolidating the post-2.0.78 YARA-X, managed-content, Palworld, public-network, authentication, and customer-workspace fixes.

## Palworld runtime split

Palworld now has two explicit runtime choices:

- `palworld.stable` — vanilla runtime, eligible on Linux or Windows;
- `palworld.windows-modded` — Windows-only runtime with managed Steam Workshop support.

The Placement Engine remains generic: operating-system eligibility comes from `RuntimeDefinition.requirements.os`, so no Palworld-specific placement hardcode was introduced.

The Windows modded runtime isolates instance state, validates server-compatible Workshop metadata, materializes `Mods/PalModSettings.ini`, injects the managed Workshop root, and retains rollback/readiness behavior through the universal content activation flow.

## YARA-X and managed content

This release includes the YARA-X administration and runtime hardening accumulated after v2.0.78:

- richer scan telemetry and threat/file details;
- managed ruleset validity preserved across rollback;
- responsive YARA-X administrative UI;
- real-time content/YARA-X UI updates;
- semantic archive validation for external uploads;
- bounded Hybrid YARA-X state ownership repair at worker startup;
- improved Hybrid runtime-event persistence and batching.

The Hybrid ownership repair is intentionally limited to:

`runtime/hybrid-agent-state/security/yara-x`

and does not widen ownership changes to the full runtime tree.

## Customer and authentication fixes

- Customer content SSE is bound to the Customer session.
- Legacy endpoints now honor `X-Capivara-Auth-Area`, allowing Customer instance deletion even when the same browser also has an active Controller session.
- Protected Customer/Controller HTML responses now send `Cache-Control: no-store`, `Pragma: no-cache`, and `Expires: 0` so stale authenticated HTML cannot retain an obsolete runtime selector after upgrades.
- Blocked local uploads can be removed by the customer.
- Managed-content status refreshes automatically.

## Network and Steam reliability

- Agent heartbeats can refresh automatically observed public IPv4 addresses on Linux, Windows, and Hybrid runtimes.
- Administrative public-network configuration exposes automatic/manual IPv4 mode.
- Steam authentication state is retained on the Agent for unattended Workshop installation flows.

## Updater regression closure

The updater remains `cap`-only:

- final validation requires `bin/cap`;
- `bin/dsm` is not required;
- the obsolete `/usr/local/bin/dsm` alias remains removed.

Regression coverage now locks this behavior.

## Universal Event Platform

Routine-event retention and Agent event ingestion received additional batching/retention work to reduce unnecessary persistence overhead while preserving the event contract.

## Validation

The consolidation PRs were validated through the applicable CI matrix, including CI, Capivara 2.0 Release Readiness, Final Customer Distributed E2E, Customer Workspace Functional Deployment, PostgreSQL Baseline v2 Isolated Deployment, P8 Administrative Observability, P0-D Structured Placement, Baseline Update Reconciliation, M10 Final E2E Release Validation, and related catalog/runtime gates.

The final pre-release cleanup also corrected the catalog regression count after publication of the new Palworld runtime: the support matrix now contains 32 published runtimes.

## Upgrade

Update an existing Controller/Hybrid installation with:

```bash
sudo cap update run
```

Remote Agents should continue to follow their configured Capivara update channel and compatibility policy.
