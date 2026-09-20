# Capivara DSM 2.0.99

Corrective placement-capacity release for Customer server provisioning.

## Fixes

- Rejects regions that do not have enough effective storage, memory or CPU for the contract resource profile instead of presenting them as eligible placement targets.
- Expands contract `resource_profile_id` into canonical placement requirements during Customer geographic placement discovery, including Minecraft profiles.
- Returns an actionable Customer-safe message when provisioning is blocked by insufficient Agent storage.
- Persists Customer health incidents without violating the canonical `alerts.scope` database constraint and preserves Customer identity for filtering and correlation.
- Improves the create-server wizard layout and status feedback so titles, help text, selectors and placement failures remain readable and responsive.
- Keeps Database Baseline v2 upgrade reconciliation compatible across PostgreSQL, MySQL/MariaDB and SQLite paths used by the alert persistence change.

## Validation

- PR #728 passed Customer Geographic Placement, Customer Health Alerting, PostgreSQL/MySQL/MariaDB isolated deployment, Update Manager Regression, Linux and Windows M10 final E2E gates.
- Local focused regression suite covering placement HTTP, Customer health, geographic placement, alert identity and create-server wizard contracts passed before release preparation.
- The fix was merged to `main` as commit `f453e81`.
