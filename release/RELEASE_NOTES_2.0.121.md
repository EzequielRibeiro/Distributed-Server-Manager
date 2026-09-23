# Capivara DSM 2.0.121

## DayZ customer fixes

- Fixes the DayZ wipe scope selector crash caused by invalid `HTMLSelectElement.add()` usage.
- Distinguishes a confirmed local Steam Query listener from public endpoint reachability.
- Avoids showing a DayZ instance as definitively offline when the Agent confirms UDP query listening but a public-IP probe times out, including NAT hairpin/loopback cases.
- Preserves the public query result separately so external reachability remains visible instead of being conflated with process health.

## Youer 26.x discovery

- Keeps Youer runtime version discovery functional when the Mohist API v2 returns an empty `versions` array.
- Falls back to the official `MohistMC/Youer` repository branch list.
- Publishes base version branches such as `26.2` and `26.3` to the Customer runtime selector.
- Filters auxiliary branches such as `26.2-spigot` from normal version selection.
- Preserves existing build discovery/fallback behavior after version selection.

## Validation

- PR #810: DayZ customer corrections and Youer 26.x discovery.
- Youer Catalog Runtime passed with the empty-API fallback regression.
- Agent public network, Customer Instance Workspace v2, Customer Workspace Functional Deployment, Final Customer Distributed E2E, Catalog Runtime Readiness, M10 Final E2E Release Validation, Capivara 2.0 Release Readiness, and CI completed successfully for the fix revision.
