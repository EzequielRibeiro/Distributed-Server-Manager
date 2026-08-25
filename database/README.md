# Capivara DSM persistence

The persistence layer supports SQLite, PostgreSQL and MySQL/MariaDB through the
backend abstraction. Clean installations use one complete schema snapshot per
backend from `database/schemas`.

## Database Baseline v2

Capivara does not maintain a historical migration chain for supported fresh
installations. Each schema file is the complete current database definition for
that backend. Database validity is determined by the baseline structure and its
checksum, not by replaying numbered migrations.

`database/schema_baseline.py` is the canonical loader for these schema snapshots.
The installed database records one `schema_baseline` metadata row containing the
baseline name and checksum. This metadata is not a migration ledger.

The supported lifecycle is intentionally simple:

```text
empty database
    -> select backend
    -> apply one complete schema baseline
    -> record baseline checksum
    -> validate required structure
    -> start services
```

Databases created by older incompatible releases are rebuilt from the supported
baseline rather than upgraded by replaying historical SQL files.

## Customer identity

Database Baseline v2 separates the technical Customer primary key from the
public Customer code:

```text
customers.id             numeric internal primary key
customers.customer_code  public immutable code, e.g. CLI-000001
```

New Customer creation never accepts an administrator-supplied Customer ID. The
database allocates the numeric primary key and Capivara derives the public code
from it. Deleted identifiers are not reused.

All internal Customer foreign keys reference `customers.id`. Public APIs,
Dashboard screens and billing integrations expose `customer_code` where a
human-facing identifier is required.

The supported Customer account chain remains:

`customers -> dashboard_users(scope_id) -> customer_account_members -> instance_access`

During the Baseline v2 conversion, `scope_id` and every Customer foreign key are
being converted to the numeric Customer primary key so database relationships do
not depend on the public `CLI-NNNNNN` representation.

A Customer login is valid only when the authenticated `dashboard_users` row is
scoped to the Customer and a matching `customer_account_members` row exists.
Account roles are `owner`, `manager` and `member`. They are deliberately
separate from the per-instance `viewer`, `operator` and `manager` permission
profiles.

`database/customer_user_repository.py` is the canonical persistence facade for
Customer users, memberships and instance grants. The last owner is protected,
and every instance grant must resolve to an instance belonging to the same
Customer.

Dashboard users are stored exclusively in the `dashboard_users` table. Create
the first administrator interactively from the console:

```bash
cap user add admin admin
```

## Database commands

```bash
dsm database init
dsm database status
dsm database check
dsm database backup /path/capivara-backup.db
```

`init` applies the complete baseline to an empty database. `status` and `check`
validate the installed baseline. Historical incremental migration is not part of
the Baseline v2 persistence contract.

JSON runtime files remain supported during the transition. Consumers are being
migrated incrementally rather than changing unrelated runtime storage contracts
at once.
