# Release upgrade contract after v2.0.63

This change keeps the next Capivara DSM release directly upgradeable from both v2.0.62 and v2.0.63.

The append-only Database Baseline v2 upgrade ledger now includes:

- v12 `universal_content_update` for `content_update_policy` and `content_update_state`;
- v13 `maintenance_restart_framework` for the M5 maintenance policy/state/run tables.

The release builder must package the canonical `update-manager/process-guard.sh` unchanged. A checksum mismatch with a fully reconciled ledger and no registered pending upgrade is rejected before DSM services are stopped or installation files are replaced. A checksum mismatch with registered pending v12/v13 upgrades is accepted for controlled reconciliation.

The next release must not require installation of v2.0.63 before updating an existing v2.0.62 controller.
