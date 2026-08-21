# Legacy audit and retirement policy

This document records the Capivara DSM 2.x legacy audit baseline. The goal is to remove dead execution paths without deleting compatibility code that is still required to upgrade supported installations.

## Retired in the 2.x cleanup

The following standalone Dashboard worker units were already classified by `update.sh` as legacy units migrated to the aggregate `dsm-dashboard-worker.service`. Keeping their unit templates in new packages caused old installations to continue exposing obsolete services, so the templates are removed:

- `dsm-backup-worker.service`
- `dsm-events-worker.service`
- `dsm-metrics-worker.service`
- `dsm-mods-worker.service`
- `dsm-server-worker.service`

The old `dashboard/workers/events_worker.sh` is also retired. It tailed the monolithic `logs/dsm.log`, carried hard-coded sample identities (`server01`, `dayz`, `survival01`) and translated text back into events. C1 Universal Event Platform and `dsm-event-queue-worker.service` are the authoritative event path in 2.x.

The aggregate Dashboard worker no longer starts `events_worker.sh`.

## Compatibility retained intentionally

Not every old-looking component is dead code. The following remain until their replacement contracts remove the dependency:

- `update.sh` legacy account migration: required to upgrade installations created before the runtime-account contract was normalized.
- `update.sh` legacy Dashboard worker migration: disables standalone worker units on upgraded hosts and moves active state to `dsm-dashboard-worker.service`.
- Dashboard server/metrics/monitor/mods/alerts/backup worker scripts: still feed compatibility state and/or runtime resources through the aggregate worker. Their old standalone systemd units are retired, but the scripts are not.
- `dashboard/notifications/discord_worker.sh`: consumes the Dashboard notification queue and is not equivalent to the core Discord sender; it is retained until notification storage is unified.

Compatibility is therefore based on a live contract, not on age or naming.

## Upgrade behavior

Existing installations may still have retired unit files in `/etc/systemd/system` from older releases. The existing updater migration disables those units with `systemctl disable --now` and enables the aggregate Dashboard worker. New packages no longer ship the retired unit templates, so clean installations cannot recreate them.

Removal of host-level stale unit files is deliberately separate from source retirement: an updater must never delete arbitrary administrator-owned units merely because their names match a broad pattern. Only explicitly retired Capivara units may be removed by a future migration with an auditable allowlist.

## Continuous gate

`tools/legacy_audit.py` and the `Legacy Audit` GitHub Actions workflow enforce the retirement list and reject common tracked backup/copy artifacts (`*.bak`, `*.backup`, `*.orig`, `*.rej`, temporary editor files). The gate also rejects any new systemd service whose description identifies it as `Legacy`.

## Architectural rule

Game-specific compatibility is allowed only where it is part of a game adapter/provider or an explicitly documented migration. Generic Controller, Placement, federation, HA/DR, API, event, configuration, observability, content and backup contracts must remain game agnostic.
