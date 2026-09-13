# Capivara DSM 2.0.49

Hotfix release for the Database Baseline v2 upgrade path used by existing Capivara 2.0 installations.

## Database Baseline v2 upgrade 8

- register Baseline Upgrade v8, `universal_content_contract_v2`;
- materialize the 11 Universal Content Contract v2 columns for existing databases that are already on ledger v7;
- reconcile the Baseline v2 marker only after the registered upgrade completes successfully;
- keep the migration idempotent when all v8 columns already exist;
- reject partially applied v8 schemas instead of silently advancing the ledger or checksum.

## Upgrade path fixed

- fix the failed PostgreSQL upgrade path observed from v2.0.46 to the cap-only release line, where the target baseline checksum changed but the upgrade ledger still reported v7 as latest;
- make preflight and apply agree on the registered v8 transition;
- update release-build regression fixtures so historical v6/v7 states are evaluated against the v8 target ledger;
- preserve the v2.0.48 cap-only compatibility bridge, allowing older v2.0.46 updaters to consume this release directly.

## Validation

- targeted Baseline/update suite passes with the v8 ledger;
- isolated PostgreSQL deployment gate passes;
- v2.0.46 PostgreSQL state upgrades from checksum `3f760706...` and ledger 7 to checksum `2a15ab4f...` and ledger 8;
- repeated migration is idempotent;
- partial v8 schema is fail-closed and rolled back;
- fresh PostgreSQL bootstrap seeds ledger v8;
- a restored pre-update PostgreSQL dump from the affected test server migrated successfully without changing customer, agent, instance, alert or event counts.

The normal Capivara update transaction remains in force: preflight, controlled service stop, filesystem backup, consistent database backup, database migration, installation validation, service restoration, and rollback on failure.
