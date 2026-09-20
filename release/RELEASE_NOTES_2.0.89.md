# Capivara DSM 2.0.89

Customer file security, archive extraction and transactional Minecraft version updates.

## Customer Files + YARA-X

- Customer file uploads now pass through YARA-X before the destination file is activated.
- Archive extraction is available in the Customer file workspace for ZIP, TAR, TAR.GZ and TGZ.
- Archives are scanned before extraction and the expanded staging tree is scanned again before materialization.
- The implementation is game-agnostic and covers Linux and Windows Agents.
- Existing confinement, managed-path and quota protections remain enforced.

## Minecraft version updates

- Adds a Customer-side Minecraft version/build compatibility preflight for catalog-supported distributions, not only NeoForge.
- Managed Modrinth/CurseForge content is classified as compatible, incompatible, unknown or disabled.
- Incompatible managed content can be temporarily disabled without deleting its assignment/history.
- Version changes require explicit risk confirmation.
- Target server binaries are installed into per-instance, per-release isolated game-data roots so one Minecraft instance cannot replace shared game-data used by another instance.
- The previous runtime is preserved until backup, materialization and readiness complete.
- Linux and Windows Agents restore the previous runtime automatically when the new runtime fails.
- The Controller commits the new Minecraft version/build identity only after the Agent reports a completed transaction.

## Previous hotfix included

Includes the v2.0.88 fix that treats virtual runtime executables such as `@java` as runtime capabilities rather than expected files during game-data integrity checks.
