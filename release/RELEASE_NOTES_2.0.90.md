# Capivara DSM 2.0.90

Hybrid Minecraft provisioning hotfix and Controller-side operation diagnostics.

## Hybrid runtime secret materialization

- Fixes privileged hybrid materialization failing with `Read-only file system: /var/lib/capivara-agent/runtime-secrets`.
- The Linux runtime secret store now derives its default from `CAPIVARA_AGENT_STATE_DIR/runtime-secrets`.
- Explicit `CAPIVARA_RUNTIME_SECRET_ROOT` continues to take precedence.
- Standard non-hybrid Agents keep the existing effective path under `/var/lib/capivara-agent`.
- The privileged materializer now propagates the helper's root-cause error instead of replacing it with the generic systemd failure.

## Controller diagnostic snapshots

- Adds Baseline v2 upgrade 18: `operation_diagnostics`.
- Provisioning failures persist bounded, sanitized `error`, `exception_type`, `traceback`, `technical_detail`, `current_step`, `error_code`, compensation and correlation metadata in the Controller.
- Technical warning/critical events can create diagnostic snapshots automatically.
- Alerts can link to a diagnostic through `diagnostic_id`.

## Dashboard alerts

- Administrative alerts with diagnostics expose **Ver detalhes**.
- The details dialog shows summary, error, technical detail, traceback, compensation and metadata.
- **Copiar diagnóstico** produces a support-ready technical snapshot without requiring Linux console commands.
- Common secret/token/password/credential fields are redacted before persistence.

## Included from v2.0.89

Includes universal YARA-X scanning for Customer Files, safe archive extraction and transactional Minecraft version updates with compatibility preflight, backup, readiness and rollback.
