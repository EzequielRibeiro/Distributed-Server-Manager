# Capivara DSM 2.0.117

## Minecraft runtime version discovery and Customer security scan polish

This patch release removes stale single-version restrictions from Minecraft Java runtime discovery and improves transient Customer security scan feedback.

### Minecraft Java Vanilla and Youer version discovery

- Replaces the pinned Minecraft Java Vanilla 1.21.8 definition with dynamic discovery from Mojang's official Java version manifest.
- Resolves the official server JAR for the exact Vanilla release selected by the customer.
- Keeps snapshots out of the normal release selector.
- Replaces the fixed Youer 1.21.1 allowlist with dynamic discovery from the MohistMC project API.
- Allows newer Youer release lines, including 26.x, to appear automatically when published upstream.
- Keeps build selection constrained to builds actually published for the selected Youer version.
- Aligns the canonical support matrix and runtime-readiness gates with the new dynamic behavior.

### Customer content security feedback

- Suppresses raw transient backend text such as `YARA-X matched content` while a security scan is still running.
- Keeps the animated `Verificando segurança…` state clean and customer-facing.
- Preserves the friendly terminal security message once content reaches blocked or security-failed state.

## Validation

- PR #795: hide transient YARA-X scan error from the Customer UI.
- PR #796: expand Minecraft Vanilla and Youer version discovery.
- PR #796 completed all triggered PR checks successfully before merge.
- Post-merge validation for #796 completed 35 workflows successfully on `main`, including CI, Minecraft Java Runtime, Youer Catalog Runtime, Catalog Runtime Readiness, Catalog Completion, Catalog Hierarchy, Database Intelligence, and Capivara 2.0 Release Readiness.
