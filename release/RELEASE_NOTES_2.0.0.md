# Capivara Distributed Server Manager 2.0.0

## Release status

Capivara DSM 2.0.0 consolidates the roadmap v3 distributed architecture into a release-ready baseline.

## Highlights

- Multi-game, multi-host distributed runtime with Controller, Placement and Agent separation.
- Linux and Windows Agent runtime parity.
- Universal Event, Configuration, Observability, Content and Smart Backup platforms.
- Automation engine and universal broadcast scopes.
- Versioned external API and real-time event streaming.
- Multi-datacenter federation with local authority preservation.
- High Availability and Disaster Recovery with quorum, fencing, failover/failback and recovery points.
- SQLite, PostgreSQL and MySQL/MariaDB persistence paths.
- Reproducible packaging and final end-to-end release readiness gates.

## Validation

The E3 release-readiness gate and main CI were green before release preparation, including install smoke tests, updater regression, Catalog v2, Linux Agent package, Windows Agent package and Phase 22 final E2E validation.

## Upgrade and rollback

Follow `docs/runbooks/capivara-2.0-operations.md`. Create a validated recovery point before upgrade. Do not silently reverse database migrations after new-version writes; restore the pre-upgrade recovery point and matching package set when rollback crosses that boundary.

## Release boundary

This release does not modify any active `/opt/dsm` installation. Deployment remains an explicit operational action.
