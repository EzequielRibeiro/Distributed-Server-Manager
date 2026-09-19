# Capivara DSM 2.0.77

Corrective release for Hybrid external content upload routing.

## Hybrid external content uploads

Hybrid Controllers now route `controller_to_agent` Artifact Transfers according to their purpose instead of treating every transfer as a backup import.

Customer external uploads with `purpose=content_upload` are now delivered to the canonical Agent quarantine path, with ownership checks, atomic copy, size and SHA-256 verification, archive validation, and the same acknowledgement contract used by remote Linux Agents.

This fixes the observed failure where valid external uploads such as `eicar-test.zip` were rejected on Hybrid installations with:

```
invalid backup_id
```

Backup import and clone flows remain unchanged. Unknown controller-to-agent artifact purposes fail closed.

## Validation

PR #647 passed CI, Hybrid Customer Workspace Parity, Final Customer Distributed E2E, Customer Workspace Functional Deployment, M10 Final E2E Release Validation, Capivara 2.0 Release Readiness, and the affected project gates.

## Included changes

- PR #647 — route Hybrid `content_upload` Artifact Transfers to quarantine instead of backup import.
- Preserve backup import/clone behavior while adding fail-closed purpose dispatch.
- Add regressions proving content uploads do not enter the backup-id path.

## Operational recovery

After v2.0.77 is published, update the Hybrid Controller normally:

```bash
sudo cap update run
```

Then retry the external content upload. The transfer should proceed through quarantine and archive validation instead of failing with `invalid backup_id`, allowing the YARA-X scan path to continue.
