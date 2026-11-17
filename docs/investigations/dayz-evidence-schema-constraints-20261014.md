# Evidence dispatch: real database constraints

Read-only inspection of the consolidated schema found two release blockers missed by simplified unit fixtures:

- `database/schemas/sqlite.sql` rebuilds `agent_instance_commands` as v3 with `CHECK(action IN ('status','doctor','start','stop','restart','remove'))`. Adding `parameters_json` alone does **not** permit `systemd_lifecycle_evidence`.
- `database/schemas/postgresql.sql` rebuilds the same table with `action VARCHAR(16)` and an equivalent action CHECK. The proposed evidence action is longer than 16 characters and is absent from the CHECK.
- The consolidated schema includes `-- source: 042_yarax_admin_operations.sql` while its current consolidated schema tracking version is 41. Evidence migration numbering was moved to 43 to avoid reusing source number 42; verify numbering against the real production migration ledger before release.

## Required changes before any release

1. Create a **complete** versioned migration for both backends. SQLite requires a safe table rebuild preserving rows, foreign keys, indexes, and any triggers. PostgreSQL requires expanding the action column width and replacing its CHECK constraint, with a verified migration transaction.
2. Validate the new action against actual freshly initialized consolidated SQLite and PostgreSQL schemas, not simplified mock tables.
3. Run Controller repository enqueue/delivery/result integration tests and confirm no changes to lifecycle command deduplication or status projection.
4. Ensure the schema migration is part of a controlled startup/upgrade process before the new repository code is enabled. Existing version-43 helper only adds a column and **is not sufficient for deployment**.
5. Validate Agent transport, permissions, and historical journal evidence on a real read-only host before using evidence to classify maintenance outcomes.

**Release status: BLOCKED.** No production migration, merge, or deployment authorized by this document.
