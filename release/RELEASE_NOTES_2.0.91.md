# Capivara DSM 2.0.91

Hotfix release for Controller diagnostic snapshots and hybrid Minecraft provisioning.

## Fixes

- Fixes the Controller alert engine startup regression introduced by the operation diagnostics feature.
- Operation diagnostics no longer depend on a package-style `core.agent_health` import and now work with the service runtime Python path.
- Keeps the v2.0.90 Controller-side diagnostic snapshots, including sanitized `error`, `exception_type`, `traceback`, technical detail, compensation and correlation metadata.
- Keeps the alert **Ver detalhes** and **Copiar diagnóstico** actions.
- Includes the hybrid runtime secret-root fix required for Minecraft Java RCON materialization.
- Includes universal Customer Files YARA-X scanning and safe archive extraction.
- Includes transactional Minecraft version-update preflight, temporary content disabling, per-instance game-data isolation, backup/readiness and rollback.

## Validation

A regression test reproduces the Python path used by `dsm-alert-engine.service` and verifies that operation diagnostics import successfully in that environment.
