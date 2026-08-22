# Smart Backup v2

Smart Backup v2 evolves C5 from a policy-driven backup engine into an operationally aware backup service.

## Goals

- Keep the existing Controller -> Agent backup pipeline as the single execution path.
- Provide policy presets without introducing game-specific behavior.
- Calculate backup health, next due time and recent reliability from persisted jobs.
- Expose the same intelligence through `cap backup-store` and `/api/backups`.
- Preserve backend neutrality across SQLite, PostgreSQL and MySQL/MariaDB.

## Presets

Presets are translated into the canonical `CapivaraBackupPolicy` before persistence. They are convenience templates, not a second policy model.

| Preset | Interval | Retention | Mode | Purpose |
| --- | ---: | ---: | --- | --- |
| `balanced` | 6h | 14 | full | General-purpose protection |
| `frequent` | 1h | 48 | full | High-value / high-change instances |
| `daily` | 24h | 14 | full | Lower-frequency environments |
| `config-safe` | 6h | 30 | config | Configuration-focused protection |

After a preset is applied, the resulting policy is revisioned and may be edited normally with `policy-set`.

## Health model

For each policy the Controller derives the following without adding another persistence table:

- current health: `disabled`, `healthy`, `due`, `overdue`, `degraded` or `never_run`;
- latest successful backup and artifact metadata;
- next expected execution time;
- pending/running work count;
- consecutive recent failures;
- recent success rate;
- latest failure message;
- remediation recommendation.

Fleet health aggregates these states and exposes an `attention_required` count for `degraded` and `overdue` policies.

## CLI

```text
cap backup-store preset-list
cap backup-store preset-list --json
cap backup-store preset-apply --instance INSTANCE --preset balanced

cap backup-store status
cap backup-store status --instance INSTANCE
cap backup-store status --agent AGENT --json
```

Existing commands remain available:

```text
cap backup-store policy-list
cap backup-store policy-set ...
cap backup-store history POLICY_ID
cap backup-store jobs ...
cap backup-store create --instance INSTANCE
cap backup-store restore --instance INSTANCE --backup BACKUP_ID
cap backup-store delete --instance INSTANCE --backup BACKUP_ID
```

## API

`GET /api/backups?kind=health` returns fleet health.

Optional filters:

```text
GET /api/backups?kind=health&instance_id=INSTANCE
GET /api/backups?kind=health&agent_id=AGENT
```

The endpoint uses the same repository evaluation as the CLI, so Dashboard and CLI cannot disagree about backup health.

## Scheduling

Smart Backup policy scheduling remains independent from the general-purpose Scheduler Jobs UI. The backup repository evaluates each enabled policy as Agents heartbeat and queues a create job when its interval is due. This keeps backup policy semantics in the backup platform while `cap scheduler` remains available for arbitrary operational jobs.

## Execution boundary

No backup artifact is executed by the Controller. The Controller stores policy and intent; the owning Agent performs create/restore/delete operations and reports state back through the authenticated distributed runtime.

The existing consistency rules remain unchanged: `live` is generic, `stopped` uses the instance lifecycle, and `quiesced` fails closed unless the runtime adapter has an explicit quiesce capability.
