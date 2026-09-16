# Capivara DSM 2.0.63

Release focused on runtime-aware placement, operational visibility for blocked customer provisioning, live server settings, isolated DayZ Workshop activation, and universal game/content update policy.

## Highlights

- Customer placement is now runtime-aware before instance creation. Regions are recalculated when the selected runtime changes, stale responses are discarded, and creation remains disabled until compatible capacity is confirmed.
- Blocked customer provisioning is surfaced to Controller operators as persistent Customer Health incidents with deduplication, severity, attempt count, runtime/region context and Agent-side technical rejection details kept administrative-only.
- Customer and Controller server-setting forms can be derived from live Agent-owned game configuration while secrets remain masked and Capivara-managed network/port values remain read-only.
- Runtime profile migration preserves persisted server-setting declarations and values instead of dropping them during profile rebuilds.
- DayZ Workshop activation now uses per-instance isolated managed content paths and private signature-key materialization on Linux, with Windows failing closed when equivalent key isolation cannot be guaranteed.
- Universal game/content update policy adds instance-level scheduling, per-content overrides, non-blocking update inventory, supervised dispatch with lease/deduplication/retry, and U9 revision-based update execution.

## Included changes

- PR #566 — derive server-setting forms from live game configuration with path-blind, Agent-owned validation.
- PR #568 — preserve server settings across runtime profile migration.
- PR #570 — make customer location placement runtime-aware and add actionable blocked-provisioning incidents for Controller operators.
- PR #571 — isolate DayZ Workshop activation and signature keys per instance.
- PR #572 — add universal game and managed-content update policy, customer scheduling and per-content overrides.

## Compatibility and upgrade notes

- Baseline v2 includes the content update policy/state additions with SQLite, PostgreSQL, MySQL and MariaDB parity; release gates validate reconciliation paths.
- The new DayZ Workshop isolation and content-update behavior span Controller and Agent code. Upgrade Controller and Agents from the same release before relying on these capabilities.
- Customer-facing placement responses remain sanitized: Agent/Node identifiers and technical rejection reasons are not exposed to the customer browser.
- No direct changes are applied to active installations by the release preparation itself; deployment continues through the normal Capivara update flow.
