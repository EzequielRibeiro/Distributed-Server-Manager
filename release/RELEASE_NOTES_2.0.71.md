# Capivara DSM 2.0.71

Test release focused on the complete managed YARA-X implementation from Y1 through Y7.

## Highlights

- Managed YARA-X engine provisioning for Linux and Windows Agents.
- Managed ruleset lifecycle with validation, integrity checks and fail-closed behavior.
- YARA-X health, capabilities and Doctor diagnostics for Agent, Hybrid and Windows runtimes.
- Structured scan telemetry persisted by the Controller and linked to managed content identity.
- Administrative YARA-X security page with health, activity and ruleset visibility.
- Allowlisted administrative operations, trusted ruleset rollback and auditable operation history.
- Semantic YARA-X alerts with health reconciliation and end-to-end lifecycle coverage.
- Dedicated `YARA-X Security Management` release-readiness gate.

## Included changes

- PR #617 — Y1 managed YARA-X engine provisioning.
- PR #619 — Y2 managed YARA-X ruleset lifecycle.
- PR #621 — Y3 YARA-X health, Doctor and capabilities.
- PR #623 — Y4 structured scan telemetry and persistence.
- PR #628 — Y5 Controller YARA-X administration UI.
- PR #630 — Y6 administrative YARA-X operations.
- PR #633 — Y7 alerts, E2E and release readiness.

## Test focus

After upgrading, validate the managed YARA-X engine and ruleset on Hybrid and standalone Agents, confirm Doctor/health state, trigger a controlled scan, verify telemetry and alerts in the Controller, and exercise the administrative operation history and rollback path.

This release is intended to validate the YARA-X implementation in a real deployment before the next production-oriented release.
