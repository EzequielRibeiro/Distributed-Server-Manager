# Capivara DSM 2.0.83

Database Intelligence release for Controller administration.

## DB1 — Database Health API

Adds a backend-aware administrative health model for PostgreSQL, MySQL/MariaDB and SQLite, including database size, version, connection pressure, query/lock indicators where supported, schema status and request latency.

## DB2 — Storage & Growth Analytics

Adds compact daily `database_metrics_daily` snapshots, table storage analytics, data/index distribution, dead-row information where available, mutation counters and 7/30/90-day storage projections.

A Controller worker captures snapshots periodically while upserting the current day, avoiding unbounded growth of the intelligence dataset itself.

## DB3 — Data Mine Dashboard

Adds `/database-intelligence.html` to the Controller administration interface with:

- database health and capacity cards;
- growth visualization;
- largest tables and index usage;
- top telemetry-producing Agents;
- top metrics by historical cardinality;
- backend capability matrix;
- retention state;
- automated insights and forecasts.

## DB4 — Retention and optimization control

Administrative actions include:

- retention preview;
- one bounded retention batch;
- manual intelligence snapshot;
- backend-appropriate `ANALYZE`.

Mutating actions are restricted to administrators and recorded through the semantic activity audit when available.

Blocking physical maintenance such as `VACUUM FULL` and `REINDEX` is intentionally not exposed as a one-click dashboard action.

## DB5 — Automated insights

The Controller derives explainable findings for storage concentration, historical/latest observability ratio, top data producers, dead-tuple pressure and query/lock contention.

## DB6 — Multi-backend parity

Baseline v2 upgrade 17 adds the compact snapshot schema across PostgreSQL, MySQL/MariaDB and SQLite. Backend-specific precision is exposed through an explicit capability matrix rather than pretending every engine offers identical statistics.

## Validation

The implementation passed the dedicated Database Intelligence gate, Baseline Update Reconciliation, PostgreSQL isolated deployment, MySQL isolated deployment, MariaDB isolated deployment, CI, M10 Final E2E Release Validation and the broader Controller test matrix.
