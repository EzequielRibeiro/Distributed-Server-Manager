# Capivara DSM 2.0.66

Patch release focused on customer-facing diagnostics for managed-content reconciliation failures.

## Highlights

- Managed-content cards now distinguish desired state from applied reconciliation state.
- The customer UI shows desired version separately from the version actually reported as installed/applied by the Agent.
- Agent-reported `reconciliation.last_error` is surfaced directly in the content card when reconciliation fails.
- Error text is bounded in the UI to avoid oversized cards while preserving the actionable cause.
- No Agent reconciliation semantics, content permissions, provider behavior, or activation rules are changed by this patch.

## Included changes

- PR #605 — show managed-content reconciliation failures in the customer workspace.

## Customer-facing behavior

A failed item that previously appeared only as:

`Não escaneado · failed`

can now show a clearer diagnostic such as:

`Desejado: ativado · Aplicado: falhou · Erro: <causa reportada pelo Agent>`.

This makes failures such as scanner/runtime/provider errors diagnosable from the customer workspace without conflating customer intent with applied state.

## Compatibility and upgrade notes

- This is a patch release after 2.0.65.
- No database migration is introduced.
- No change is made to content reconciliation or security policy; this release only exposes already-persisted reconciliation details to the customer UI.
- Controllers should be upgraded to 2.0.66 to receive the UI fix. Agent upgrades are still recommended for version parity, but the diagnostic field itself already originates from the existing Agent reconciliation report.
- No direct changes are applied to an active `/opt/dsm` installation by release preparation itself; deployment continues through the normal Capivara updater.
