# Capivara DSM 2.0.53

Maintenance release focused on customer resource visibility and telemetry quality.

## Highlights

- Customer instance storage limits now resolve from the selected Catalog Resource Profile when persisted workspace limits are incomplete, restoring `used / maximum` storage visibility and File Manager quota enforcement for existing instances such as DayZ and Palworld.
- Linux per-instance CPU and memory telemetry now measures the complete systemd unit through `CPUUsageNSec` and `MemoryCurrent`, fixing wrapper-based runtimes such as Palworld while preserving the MainPID/proc fallback.
- Customer instance telemetry now provides richer CPU, memory, network RX/TX, players and latency charts with current/average/peak summaries, Y-axis scale and units, X-axis timestamps, current-point markers and explicit unavailable states.
- Controller home and Agent Details telemetry charts now use the same richer operational presentation with scales, timestamps, summaries, observed windows, sample counts and explicit empty states.

## Included changes

- PR #469 — resolve customer storage quota/resource limits from the Catalog Resource Profile.
- PR #475 — rebased integration of the systemd unit CPU/memory telemetry correction from PR #464.
- PR #476 — rebased integration of the customer telemetry chart improvements from PR #463.
- PR #477 — rebased integration of the Controller and Agent Details telemetry chart improvements from PR #467.
- Retains the Hybrid node-activity history correction shipped in v2.0.52.

## Compatibility and scope

- No new database baseline migration is required by these changes.
- Explicit persisted workspace resource limits continue to override Catalog profile fallbacks.
- Palworld REST player-count/query integration is not part of this release.
- Universal Content Activation Layer work remains outside this release.
