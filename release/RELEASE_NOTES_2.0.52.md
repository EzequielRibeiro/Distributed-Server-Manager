# Capivara DSM 2.0.52

## Summary

Capivara DSM 2.0.52 is a focused observability maintenance release for Hybrid nodes.

## Fixed

- Hybrid instance telemetry now projects accepted instance samples into Universal Observability, so node-activity charts on `agent-details.html` accumulate real historical series instead of showing only instantaneous values.
- Historical node metrics now include running/total instances, instance storage usage, player aggregates when a game query is available, and host storage free bytes.
- Hybrid ownership checks remain fail-closed: only telemetry from instances owned by the embedded Hybrid Agent is projected.

## Validation

- 27/27 targeted Hybrid, observability, dashboard and telemetry tests passed before merge.
- Release builder passed before merge.
- PR #471 completed the full repository CI successfully, including Universal Observability, P8 Administrative Observability, PostgreSQL isolated deployment, Final Customer Distributed E2E and the general CI gate.

## Scope

This release contains only changes already merged to `main` after v2.0.51. Open work such as customer storage-quota fallback, Palworld systemd resource telemetry and the richer telemetry chart UI remains outside this release until its own PR is merged.
