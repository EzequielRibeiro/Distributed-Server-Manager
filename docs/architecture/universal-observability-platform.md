# C3 — Universal Observability Platform

C3 establishes one canonical metrics plane for Capivara DSM. It replaces the architectural assumption that each worker owns an isolated JSON metrics file with a Controller-side, queryable, multi-backend time-series contract while preserving legacy worker state for compatibility.

## Contract

Every sample is normalized as `CapivaraMetricSample` with a deterministic `sample_id`, authenticated `agent_id`, optional `instance_id`, metric name/type, finite numeric value, unit, dimensions and collection timestamp. Supported scopes are `agent` and `instance`; supported primitive types are `gauge` and `counter`.

Agent identity is supplied by the authenticated heartbeat boundary. An Agent cannot publish a metric for another Agent, and instance-scoped samples are accepted only when the instance belongs to the authenticated Agent.

## Collection and transport

The Linux Agent collects dependency-free host metrics from Linux kernel interfaces and its existing runtime telemetry. Initial universal metrics include system load, memory, root filesystem, network counters, uptime, thermal zones, Capivara runtime counters/queues/durations and instance runtime health.

Metrics travel with the already-authenticated Agent heartbeat. The Controller never executes remote shell commands to collect metrics. Agent inventory remains operational state; `observability_samples` is historical telemetry.

Future game adapters may publish game-specific measurements using the same envelope (players, tickrate, FPS or application-specific gauges) without adding game-specific branches to the Controller.

## Persistence

Migration `034_universal_observability.sql` has equivalent SQLite, MySQL/MariaDB and PostgreSQL variants.

- `observability_samples` is append-oriented historical storage keyed by `sample_id`.
- `observability_latest` is a compact latest-value projection keyed by Agent, subject, metric and dimensions.

Duplicate delivery is idempotent. Out-of-order samples remain in history but do not replace a newer latest projection.

## Query surfaces

Administrative API:

- `GET /api/observability?mode=latest`
- `GET /api/observability?mode=history`
- `GET /api/observability?mode=summary`

CLI:

- `cap observe latest`
- `cap observe history`
- `cap observe summary`
- `cap observe prune --before <ISO8601> --yes`

Filters include Agent, instance, metric name and bounded time/row windows where appropriate.

## Boundaries

C3 owns collection, validation, persistence, latest projection, bounded aggregation, querying and retention primitives. It does **not** implement alert thresholds, automation rules or WebSocket streaming. Those consume C3 later through the Automation/Broadcast and real-time/API phases. Universal Events C1 remains the event plane; metrics are not converted into noisy per-sample events.

Legacy files under `dashboard/state` and `monitor/metrics` remain compatibility inputs during progressive migration; C3 does not delete them.
