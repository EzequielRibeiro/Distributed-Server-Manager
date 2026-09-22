# Capivara DSM 2.0.119

## Youer runtime discovery fallback hardening

This hotfix completes the resilience work for Minecraft Java Youer discovery when MohistMC build-list APIs are unavailable or degraded.

### Youer runtime discovery

- Keeps published Youer versions visible independently of build-list availability.
- Exports and configures the legacy MohistMC API fallback consistently in both Dashboard and installer resolver bridges.
- Uses the MohistMC canonical `builds/latest/download` route for unpinned selections when build listing is unavailable.
- Prevents the Customer selector from masking an empty dynamic runtime response as the generic `Versão atual / recomendada` option.
- Preserves dynamic support for newer Youer release lines, including 26.x when published upstream.
- Keeps pinned build selections strict: explicitly requested builds still require a real build listing match.

## Validation

- PR #802: harden Youer discovery when build APIs fail.
- All 32 triggered PR checks for #802 passed.
- Post-merge validation on `main` completed 30 workflows successfully, including CI, Youer Catalog Runtime, Minecraft Java Runtime, Catalog Completion, Catalog Hierarchy, Catalog Agent Runtime Parity, Final Customer Distributed E2E, Customer Geographic Placement, Browser Session Security, and Capivara 2.0 Release Readiness.
