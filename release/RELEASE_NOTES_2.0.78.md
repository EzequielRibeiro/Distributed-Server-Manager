# Capivara DSM 2.0.78

Corrective release for Hybrid external content quarantine path resolution.

## Hybrid quarantine root

Hybrid Controllers now explicitly set the embedded Agent game-data root to:

```
/opt/dsm/runtime/hybrid-agent-state/game-data
```

This prevents external content uploads from falling back to the remote-Agent default:

```
/var/lib/capivara-agent/game-data
```

which caused customer uploads to fail with:

```
[Errno 13] Permission denied: '/var/lib/capivara-agent/game-data'
```

The fix keeps external-upload quarantine, Universal Content, and the embedded Hybrid runtime under the same managed state root without relaxing permissions on the remote-Agent filesystem.

## Validation

PR #649 passed CI, Agent Game Data, Customer Workspace Functional Deployment, Final Customer Distributed E2E, PostgreSQL Baseline v2 Isolated Deployment, M10 Final E2E Release Validation, Capivara 2.0 Release Readiness, and the affected project gates.

## Included changes

- PR #649 — define `CAPIVARA_GAME_DATA_ROOT` for the embedded Hybrid runtime before runtime modules are imported.
- Add regression coverage that guards the Hybrid game-data root initialization order.

## Operational recovery

After v2.0.78 is published, update the Hybrid Controller normally:

```bash
sudo cap update run
```

Then retry the external upload. The artifact should be written under the Hybrid quarantine path and continue through archive validation and the YARA-X security gate.
