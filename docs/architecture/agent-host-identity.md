# Agent host identity

Linux Agents use a canonical host identity materialized by the privileged runtime-identity reconciliation service.

The privileged reconciler reads `/etc/machine-id` and the platform DMI `product_uuid` when available, falling back to stable network adapter addresses only when the platform UUID is unavailable. It writes the resulting `sha256:` identity to `/var/lib/capivara-agent/host-identity` as `root:capivara-agent` with mode `0640`.

The unprivileged `capivara-agent` runtime reads this canonical file and reports it in heartbeat inventory. Direct host probing remains only as a backward-compatible fallback for installations that have not yet materialized the canonical file.

This prevents host identity from changing merely because the same code is executed as `root` versus the `capivara-agent` service account.
