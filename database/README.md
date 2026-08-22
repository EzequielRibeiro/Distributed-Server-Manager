# Capivara DSM persistence

The persistence layer uses SQLite from the Python standard library. It does
not require a separate database server and is suitable for Controller, Agent
and hybrid installations.

The default database is stored at `data/capivara.db`. Clean installations use
one complete schema per backend from `database/schemas`. Historical incremental
migrations and upgrades of databases created by old releases are unsupported.

Dashboard users are stored exclusively in the `dashboard_users` table. Create
the first administrator interactively from the console:

```bash
cap user add admin admin
```

The `cap instance create-aurora` demonstration command creates the active
`aurora` customer user and its ownership links in SQLite. There is no
`users.conf` authentication fallback.

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
