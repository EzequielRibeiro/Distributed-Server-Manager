# Capivara DSM 2.0.51

Release focused on Customer content management, Steam Workshop resolution, and reliable customer backup deletion.

## Customer content and Steam Workshop

- exposes the Customer content API through the distributed workspace contract;
- resolves Steam Workshop references safely for supported runtimes instead of leaving Workshop metadata unresolved;
- declares Workshop identity for DayZ and Project Zomboid runtimes and enables their Workshop capability;
- keeps content activation behind the existing runtime/provider and authorization boundaries.

## Customer backup deletion

- fixes delete/retry jobs so `command_id` remains the job identity while `backup_id` can be reused as the artifact reference;
- removes stale `UNIQUE` constraints/indexes on `backup_jobs.backup_id` for SQLite, PostgreSQL, MySQL and MariaDB;
- adds Baseline Upgrade v9 (`backup_job_retry_identity_repair`) so existing installations are repaired safely;
- removes successfully deleted backups from the effective Customer backup inventory, latest-backup projection, backup health and scheduler views;
- preserves failed delete operations as history without hiding an artifact that still exists;
- scopes delete tombstones by instance and backup id to prevent cross-instance masking.

## Release/update compatibility

- updates the release-builder Baseline regression payload to include upgrade v9;
- validates the v9 path through Baseline Update Reconciliation and isolated PostgreSQL deployment;
- preserves reproducible release packaging and Update Manager compatibility.

## Validation

- Universal Smart Backup: passed;
- Backup Restore Dashboard Flow: passed;
- Customer Instance Workspace v2 and Customer Workspace Functional Deployment: passed;
- Final Customer Distributed E2E: passed;
- Baseline Update Reconciliation and PostgreSQL Baseline v2 Isolated Deployment: passed;
- Update Manager Regression, including reproducible release build: passed;
- full CI for the backup-fix PR: passed.

This release includes all changes merged after v2.0.50 through the customer backup deletion fix.
