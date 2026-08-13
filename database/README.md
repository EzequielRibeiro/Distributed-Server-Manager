# Capivara DSM persistence

The persistence layer uses SQLite from the Python standard library. It does
not require a separate database server and is suitable for Controller, Agent
and hybrid installations.

The default database is stored at `data/capivara.db`. Migration files are
immutable and live in `database/migrations`.

Dashboard users are stored exclusively in the `dashboard_users` table. Create
the first administrator interactively from the console:

```bash
dsm user add admin admin
```

The `dsm instance create-aurora` demonstration command creates the active
`aurora` customer user and its ownership links in SQLite. There is no
`users.conf` authentication fallback.

```bash
dsm database init
dsm database migrate
dsm database status
dsm database check
dsm database backup /path/capivara-backup.db
```

The installer initializes the database after writing the machine-specific
configuration. The updater applies pending migrations before restarting the
services. A migration failure therefore uses the existing updater rollback.

JSON runtime files remain supported during the transition. Consumers will be
migrated incrementally rather than changing their storage contracts at once.
