# E3 — Capivara DSM 2.0 Final Consolidation & Release Readiness

## Goal

Turn the completed distributed architecture into a release-ready Capivara DSM 2.0 baseline without introducing game-specific shortcuts or modifying an active `/opt/dsm` installation.

## Release invariants

A release candidate is eligible only when all of the following are true:

1. Controller, Placement, Agent and Instance Runtime end-to-end gates pass.
2. C1–C5 universal platforms pass their dedicated regression gates.
3. D1 Automation/Broadcast and D2 Real-Time API gates pass.
4. E1 Multi-Datacenter Federation and E2 HA/DR gates pass.
5. Linux and Windows Agent packages are reproducible and validated.
6. Database migrations remain monotonic and supported backends preserve schema parity.
7. Upgrade validation proves that an existing supported installation can move forward without destructive implicit migration.
8. No release blocker of severity critical/high remains open.
9. Security validation finds no committed credential, unsafe arbitrary shell contract, path traversal regression or authentication bypass in release surfaces.
10. Documentation describes install, upgrade, backup/restore, federation, HA/DR and rollback procedures.

## E3 workstreams

### E3.1 Architecture consolidation
Audit cross-platform contracts and remove contradictory/deprecated documentation. Generic layers must remain game-agnostic.

### E3.2 Upgrade and migration readiness
Validate sequential database migrations, configuration compatibility, package upgrade paths and rollback boundaries.

### E3.3 Security hardening
Run secret scanning, dependency/static checks available in CI, authentication/RBAC regressions, archive/path safety tests and API abuse boundaries.

### E3.4 Reliability and scale
Exercise concurrent instances, event/metric retention, automation idempotency, backup pressure, federation degradation and HA failover recovery.

### E3.5 Packaging matrix
Validate Controller plus Linux/Windows Agent artifacts and reproducibility from a clean checkout.

### E3.6 Operational documentation
Freeze runbooks for installation, upgrade, federation, failover/failback, DR restore and incident rollback.

### E3.7 Release manifest
Generate a machine-readable readiness manifest containing mandatory gates and their expected evidence.

### E3.8 Release candidate gate
The final CI workflow must aggregate mandatory validation. Passing E3 means release-ready; it does not automatically publish a GitHub Release or modify production.

## Completion criterion

E3 is complete when the release-readiness gate is green on the final branch head, the full existing CI is green, release documentation and manifest are present, and the changes are merged to `main`. Release publication remains a separate explicit administrative action.
