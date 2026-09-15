# Capivara DSM 2.0.61

Maintenance release focused on customer placement labels, browser geolocation policy, and Hybrid configuration reconciliation.

## Highlights

- Customer placement now displays country and state instead of city, for example `🇧🇷 Brasil - São Paulo · ~18 ms · ★ Servidor recomendado`.
- Datacenter city remains stored as administrative metadata but is no longer shown in the public location label.
- The dashboard Permissions-Policy now allows geolocation only from the same origin (`geolocation=(self)`), while camera and microphone remain disabled.
- The placement client still does not prompt for location automatically; it only uses coordinates when the browser permission is already granted.
- Hybrid mode now reconciles Controller configuration desired state into the local Agent runtime.

## Included changes

- PR #560 — apply Controller configuration desired state in Hybrid mode.
- PR #561 — show country/state in placement and allow same-origin geolocation for latency estimation.

## Compatibility and upgrade notes

- No manual edits under `/opt/dsm` are required.
- Existing Datacenter city metadata is preserved.
- Upgrade through the canonical `cap update` flow.
