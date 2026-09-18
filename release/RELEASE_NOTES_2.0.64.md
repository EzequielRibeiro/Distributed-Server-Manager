# Capivara DSM 2.0.64

Release focused on the complete M1→M10 operational roadmap: universal maintenance, native game maintenance adapters, universal managed-content capabilities, Minecraft modpack lifecycle, final Linux/Windows distributed E2E validation, and a corrected Baseline v2 upgrade path after 2.0.63.

## Highlights

- Universal Maintenance & Restart Framework schedules fixed/interval maintenance with timezone support, warnings, native save where supported, and coalesces game updates, content updates and restart-required configuration into a single downtime window.
- DayZ gains native restart orchestration through Agent-owned `messages.xml`, including countdown, graceful shutdown, Controller↔Agent transport, fail-closed timeout handling and Linux/Windows parity.
- Native maintenance capabilities are now canonical across the shipped RuntimeDefinitions. Minecraft Java uses typed local RCON for broadcast/save where supported, Palworld uses typed REST administration, and unsupported operations remain fail-closed.
- Universal Mod Management introduces a canonical provider/action capability matrix for Steam Workshop, Modrinth, CurseForge, GitHub, HTTP/HTTP Archive and External Upload. Customer actions are server-authoritative and capability-driven.
- Minecraft modpacks are exposed as versioned managed bundles with customer-safe component details, revision history, update diff, managed/customized classification and atomic full-bundle rollback.
- Managed bundle children cannot be mutated independently through the customer API; update and rollback remain parent-modpack operations with server/provider authority.
- Final M10 validation composes Universal Content, real Controller↔Agent maintenance, native DayZ restart, M7 maintenance regressions, M9 modpack regressions, baseline upgrade checks and release readiness across Linux and Windows.
- DayZ and Project Zomboid content activation is explicitly tested for deterministic rehydration after Agent-process restart without argument/configuration drift.
- Baseline v12/v13 reconciliation fixes the failed 2.0.62 → 2.0.63 upgrade class and supports the next fixed patch through registered append-only migrations and fail-closed preflight validation.

## Included changes

- PR #573 — M5 Maintenance & Restart Framework.
- PR #575 — timezone support across scheduled operations.
- PR #578 — M6 DayZ native restart via `messages.xml`.
- PR #579 — Baseline v12/v13 release-path reconciliation.
- PR #581 — M7 native maintenance adapters and canonical capability inventory.
- PR #583 — M8 Universal Mod Management capabilities.
- PR #585 — M9 complete Minecraft modpack management.
- PR #587 — M10 final E2E, Linux/Windows parity and release validation.

## Operational flow

The canonical maintenance/content path is now:

`Customer/Admin → Controller/RBAC → desired state → provider/revision → U7 scan → activation → maintenance/coalescing → native save/shutdown when supported → update/config/content apply → RuntimeSpec → start → Doctor/readiness → persisted reconciled state`.

The browser never becomes authority for update artifact URLs, hashes or versions. Game-specific materialization remains Agent-owned and unsupported capabilities fail closed.

## Compatibility and upgrade notes

- This release is intended to be the corrected patch after 2.0.63. The Baseline v2 upgrade ledger includes the content-update and maintenance schema extensions required to reconcile older v11 installations before mutation.
- Direct upgrade from 2.0.62 to 2.0.64 is covered by the baseline upgrade regression path; installation of 2.0.63 first is not required.
- Controllers and Agents should be upgraded to the same release before relying on the new maintenance/content semantics.
- SQLite, PostgreSQL, MySQL and MariaDB schema parity remains a release invariant.
- Linux and Windows Agent packages are built and validated from the exact approved release SHA.
- No direct changes are applied to an active `/opt/dsm` installation by release preparation itself; deployment continues through the normal Capivara updater.
