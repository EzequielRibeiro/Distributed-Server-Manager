# Capivara DSM 2.0.103

Minecraft runtime recovery and contract-policy consistency release.

## Fixes

- Repairs stale Minecraft Java instance-private runtime seeds during reprovisioning, restoring provider-owned files such as `server.jar` without overwriting target-owned world/config state.
- Prevents Customer creation of Minecraft runtimes that are not permitted by the selected contract. Minecraft Padrão remains limited to Vanilla Java/Bedrock; modified runtimes such as Fabric, Forge, NeoForge, Paper, Quilt and Youer require Minecraft Modificado.
- Adds the same contract/runtime enforcement to the backend, so direct API calls cannot bypass the UI rule.
- Adds an administrative Minecraft product selector backed by the catalog, with canonical `standard` / `modified` metadata and entitlements.
- Improves the runtime cards so incompatible distributions are visibly blocked with the reason `Exige Minecraft Modificado`.

## Legacy repair

- Adds Baseline Upgrade 20, `legacy_minecraft_contract_products`.
- Legacy Minecraft contracts created before product variants existed are backfilled to `modified` only when they have no explicit `product_variant/content_mode` and already own an instance using a modified-only runtime.
- Explicitly Standard contracts are never promoted automatically.
- Existing contract metadata such as resource profiles is preserved.

## Validation

- PR #739 validated stale Minecraft runtime seed repair with Linux/Windows parity.
- PR #741 passed Customer Workspace, Universal Content, contract/runtime gating, functional deployment and distributed E2E coverage.
- PR #742 passed all 22 triggered checks, including CI Gate, PostgreSQL, MySQL, MariaDB, Linux/Windows final E2E, Final Customer Distributed E2E, M10 and Release Readiness.
