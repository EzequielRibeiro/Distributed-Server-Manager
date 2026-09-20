# Database Intelligence — DB1 to DB6

Database Intelligence is the Controller-side administrative surface for database health, storage growth, data generation, retention and backend parity. It is intentionally not a generic SQL console and never exposes credentials or arbitrary query execution.

## DB1 — Database Health API

The Controller exposes a backend-aware health model with database size, server version, connection utilization, long-running query count where available, waiting locks where available, schema status and request latency.

Read access is limited to `admin` and `controller` roles.

## DB2 — Storage & Growth Analytics

`database_metrics_daily` stores compact daily snapshots for the database and individual tables. The snapshot worker runs periodically and upserts the current day, so frequent worker execution does not create unbounded snapshot rows.

The growth model includes:

- total database size;
- table data and index sizes where the backend exposes them;
- row/dead-row and mutation counters where available;
- average observed daily growth;
- 7/30/90-day linear storage projections.

## DB3 — Data Mine Dashboard

`/database-intelligence.html` presents:

- health and capacity cards;
- database growth graph;
- largest tables;
- top telemetry-producing Agents;
- top metric cardinality;
- index efficiency;
- retention state;
- backend capability parity;
- automated insights.

The page uses the canonical Controller session boundary and does not run direct database queries from the browser.

## DB4 — Retention / Optimization Control

Admin-only maintenance actions are deliberately bounded:

- retention preview;
- one bounded retention batch;
- compact intelligence snapshot;
- backend-appropriate `ANALYZE`.

Blocking physical maintenance such as `VACUUM FULL` and `REINDEX` is never exposed as a one-click action. The dashboard may recommend a maintenance window, but execution remains an explicit operational task.

Every mutating action is written to the semantic activity audit when available.

## DB5 — Automated Insights & Forecasts

The Controller derives explainable insights from current database metadata instead of using opaque scoring. Current rules identify:

- storage concentration;
- historical-vs-latest observability ratio;
- largest telemetry producer;
- dead-tuple pressure;
- active query/lock contention.

Forecasts use the compact daily snapshot series and clearly remain projections rather than measured future usage.

## DB6 — Multi-backend Parity

The same API and UI contract supports PostgreSQL, MySQL/MariaDB and SQLite.

Backend-specific capabilities are reported explicitly. PostgreSQL provides the richest lock/index statistics; MySQL/MariaDB provide information-schema storage data and optional InnoDB index sizing; SQLite provides health, logical table counts, database file size and snapshots while marking unsupported precision capabilities as unavailable.

Baseline v2 upgrade 17 creates `database_metrics_daily` across all supported backends.

## Configuration

- `DSM_DATABASE_INTELLIGENCE_SNAPSHOT_SECONDS` — snapshot worker interval, default 3600 seconds.
- `DSM_OBSERVABILITY_RETENTION_DAYS` — observability retention, default 7 days.
- `DSM_OBSERVABILITY_HISTORY_INTERVAL_SECONDS` — historical bucket, default 300 seconds.
- `DSM_OBSERVABILITY_RETENTION_BATCH_SIZE` — bounded delete batch, default 5000 rows.
- `DSM_OBSERVABILITY_RETENTION_WORKER_SECONDS` — retention worker interval, default 300 seconds.
