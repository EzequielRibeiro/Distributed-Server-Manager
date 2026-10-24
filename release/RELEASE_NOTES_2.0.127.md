# Capivara DSM 2.0.127

## Minecraft NeoForge: authenticated current-runtime diagnosis

- PR #939 (issue #935): authenticated recovery evidence ingestion and current NeoForge attestation for Controller and hybrid Agent.
- The Agent verifies the currently installed NeoForge libraries and canonical launcher arguments before providing a present-state attestation.
- Support historical hybrid instance records without `content_root`, requiring one unambiguous locally installed NeoForge build and successful launcher verification.
- The Controller verifies Agent ownership and persists immutable attestation events with idempotency.
- The customer workspace distinguishes the verified current runtime from a historical provisioning failure at 99%; historical failure records are preserved rather than silently cleared.

## Validation and deployment boundary

- PR #939: 36/36 GitHub Actions workflows passed before merge.
- Isolated HTTP authentication, SQLite persistence/idempotency, and customer API projection checks were completed; read-only actual filesystem collector verified Minecraft 005 NeoForge 26.1.2.94.
- The full actual-collector → HTTP → database chain and independent human review were not completed before PR merge. Validate these separately before deployment.
- **Release candidate only:** this preparation does not publish a tag or GitHub Release and does not update or restart running services.
- The current updater may drain/restart managed game servers. Schedule a dedicated operational rollout after reviewing maintenance impact, backups, and rollback strategy.
