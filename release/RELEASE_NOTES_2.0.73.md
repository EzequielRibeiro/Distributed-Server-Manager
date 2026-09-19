# Capivara DSM 2.0.73

Corrective release for the v2.0.72 Dashboard startup and updater incident paths.

## Dashboard startup fix

The canonical Dashboard entrypoint `server_part21.py` now resolves the Controller authentication function through the complete composition chain to `server_part17`.

This fixes the v2.0.72 startup failure:

```
AttributeError: module 'server_part18' has no attribute '_controller_authenticate'
```

The failure could occur after a successful database upgrade, causing post-update Dashboard readiness to fail even though Baseline v2 was already healthy at upgrade 14/14.

## Update release selection

The DSM updater no longer trusts GitHub `/releases/latest` as the canonical DSM release source.

Standalone Agent releases such as `agent-windows-v2.0.72` can be published after the Controller release and temporarily become GitHub's latest release. Version 2.0.73 selects only canonical `vX.Y.Z` releases that include both:

- `capivara-dsm-X.Y.Z.tar.gz`
- `capivara-dsm-X.Y.Z.tar.gz.sha256`

Standalone Linux/Windows Agent releases are ignored by the DSM updater.

## PostgreSQL rollback diagnostics

PostgreSQL backup/restore failures now retain bounded stderr from `pg_dump` and `pg_restore` in the surfaced database error instead of reporting only a generic non-zero exit status.

This materially improves rollback diagnostics without echoing command arguments.

## Validation

The hotfix passed:

- CI Gate
- Update Manager Regression
- PostgreSQL Baseline v2 Isolated Deployment
- Baseline Update Reconciliation
- YARA-X Security Management
- M10 Linux and Windows final E2E
- Final Customer Distributed E2E
- Customer Workspace Functional Deployment
- Release Readiness and supporting project gates

## Included changes

- PR #637 — Dashboard YARA-X composition startup, DSM release selection hardening, and PostgreSQL restore diagnostics.

## Operational recovery

A host that reached v2.0.72 files and a healthy Baseline v2 upgrade 14/14 but failed only on Dashboard startup should upgrade forward to v2.0.73.

Do not manually downgrade the Baseline v2 database from upgrade 14.

After v2.0.73 is published, use the normal updater:

```bash
sudo cap update run
```
