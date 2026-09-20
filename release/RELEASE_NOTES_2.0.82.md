# Capivara DSM 2.0.82

Corrective release to bound Controller database growth from observability history.

## Observability storage control

Production analysis found that historical observability storage was dominating the PostgreSQL database. The latest-value projection remained compact, while every heartbeat sample was still appended to historical storage.

This release changes historical persistence while preserving real-time state:

- `observability_latest` continues to update on every accepted heartbeat;
- dynamic metrics are persisted to history at most once per five-minute bucket by default;
- stable inventory-style metrics such as total memory, total disk capacity and Agent PID are persisted only when their value changes;
- historical observability retention defaults to seven days;
- cleanup runs in bounded batches to avoid one large delete transaction;
- retention is executed automatically by a Controller worker integrated with the existing dashboard worker group.

## Tunable settings

The defaults may be adjusted with:

- `DSM_OBSERVABILITY_HISTORY_INTERVAL_SECONDS`
- `DSM_OBSERVABILITY_RETENTION_DAYS`
- `DSM_OBSERVABILITY_RETENTION_BATCH_SIZE`
- `DSM_OBSERVABILITY_RETENTION_WORKER_SECONDS`

## Expected impact

For Agents using a 30-second heartbeat, five-minute historical buckets reduce normal dynamic history cardinality by roughly 10x while maintaining real-time latest values. Static metrics are reduced further because unchanged values are no longer repeatedly appended.

## Safety

This release does not automatically run `VACUUM FULL`, `REINDEX`, or any other blocking physical-space reclamation operation. Existing historical rows are pruned logically in bounded batches. Physical database compaction can be scheduled separately after retention has reduced the live dataset.
