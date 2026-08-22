# Capivara DSM persistence

The persistence layer supports SQLite, PostgreSQL and MySQL/MariaDB through the
backend abstraction. Clean installations use one complete schema per backend
from `database/schemas`; historical incremental migrations and upgrades of
databases created by old releases are unsupported.

## Customer user lifecycle

The historical 006/007 migration responsibilities are represented in the
consolidated schemas. The supported Customer identity chain is:

`customers -> dashboard_users(scope_id) -> customer_account_members -> instance_access`

A Customer login is valid only when the authenticated `dashboard_users` row is
scoped to the Customer and a matching `customer_account_members` row exists.
Account roles are `owner`, `manager` and `member`. They are deliberately
separate from the per-instance `viewer`, `operator` and `manager` permission
profiles. Customer-facing requests derive the Customer ID from the authenticated
session; callers cannot select another Customer scope.

`database/customer_user_repository.py` is the canonical persistence facade for
Customer users, memberships and instance grants. The older
`customer_team_repository.py` remains the lower-level compatibility
implementation while callers migrate to the canonical facade. The last owner is
protected, and every instance grant must resolve to an instance belonging to the
same Customer.

Dashboard users are stored exclusively in the `dashboard_users` table. Create
the first administrator interactively from the console:

```bash
cap user add admin admin
```

The `cap instance create-aurora` demonstration command creates the active
`aurora` customer user and its ownership links. There is no `users.conf`
authentication fallback.

```bash
dsm database init
dsm database migrate
dsm database status
dsm database check
dsm database backup /path/capivara-backup.db
```

The installer validates connectivity before persistent installation, then
applies and validates the consolidated schema before starting services. The
`migrate` command is retained as an idempotent schema-validation alias; it does
not execute a historical upgrade chain.

JSON runtime files remain supported during the transition. Consumers will be
migrated incrementally rather than changing their storage contracts at once.
