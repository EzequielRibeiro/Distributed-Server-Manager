# Capivara DSM 2.0.75

Corrective release for Linux Hybrid Universal Content activation.

## Privileged Hybrid activation

Universal Content activation on Linux Hybrid Controllers now routes RuntimeSpec materialization through the existing privileged materialization bridge instead of calling the systemd materializer directly from the unprivileged dashboard worker.

This fixes the observed activation failure:

```
activation failed and rollback failed: [Errno 13] Permission denied:
'/etc/systemd/system/.capivara-instance-cli-000001-dayz-001.service.<pid>.tmp'
```

The Hybrid worker continues to materialize instance-scoped content files in the Agent runtime context, while root-only systemd unit updates are delegated to the existing privileged helper service.

## Rollback safety

Activation rollback now uses the same privileged materialization boundary, so both forward activation and rollback respect the same systemd privilege model.

## Validation

PR #641 passed the full affected matrix, including:

- CI
- Universal Content Platform
- Universal Content E2E
- Agent Instance Runtime
- External Controller Agent E2E
- M10 Final E2E Release Validation
- Final Customer Distributed E2E
- M8 Universal Mod Management
- Maintenance Restart Framework
- Capivara 2.0 Release Readiness
- Baseline Update Reconciliation

## Included changes

- PR #641 — route Linux Hybrid content activation and rollback through `privileged_materialization`.

## Operational recovery

After v2.0.75 is published, update the Hybrid Controller normally:

```bash
sudo cap update run
```

Then allow Universal Content reconciliation to retry the pending VPPAdminTools activation. No manual changes under `/etc/systemd/system` are required.
