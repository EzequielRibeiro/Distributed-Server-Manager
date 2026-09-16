# Database Baseline v2 release preflight

Before a Capivara DSM update stops Controller services or replaces files, the target package must classify the currently installed database using the target release's own Baseline v2 upgrade registry.

A checksum mismatch is upgradeable only when the database has a valid upgrade ledger and the target package reports registered pending upgrades, or when a recognized pre-ledger compatibility bridge applies. A checksum mismatch with an existing ledger and no pending registered upgrade is incompatible and must stop the update before service shutdown.

The next patch release after v2.0.63 carries upgrade 12 for the universal content update schema and upgrade 13 for the maintenance/restart framework. This preserves direct upgrades from v2.0.62 as well as reconciliation of v2.0.63 databases that already contain the content-update tables but have a ledger ending at version 11.
