# Capivara DSM 2.0.118

## Youer runtime discovery hotfix

This hotfix hardens Minecraft Java Youer version and build discovery after the dynamic discovery changes introduced in 2.0.117.

### Youer discovery resilience

- Keeps the customer-facing Youer version list available even when a per-version build endpoint temporarily fails.
- Separates version discovery from build discovery so the selector does not collapse to the generic `Versão atual / recomendada` fallback.
- Uses MohistMC API v2 as the primary build source.
- Falls back to the established official `api.mohistmc.com/project/youer` endpoint when v2 build discovery is unavailable.
- Preserves dynamic support for newer Youer release lines, including 26.x when published upstream.
- Keeps build selection constrained to builds actually returned by MohistMC.
- Uses the legacy official download endpoint as an artifact URL fallback when a build object does not expose a direct URL.

## Validation

- PR #799: harden Youer version discovery fallback.
- All triggered PR checks for #799 passed.
- Post-merge validation on `main` completed 24 workflows successfully, including CI, Youer Catalog Runtime, Minecraft Java Runtime, Catalog Completion, Catalog Hierarchy, Capivara 2.0 Release Readiness, and related runtime/catalog gates.
