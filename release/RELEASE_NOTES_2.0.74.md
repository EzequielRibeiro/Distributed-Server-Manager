# Capivara DSM 2.0.74

Corrective release for managed YARA-X operation on Linux Hybrid Controllers.

## Hybrid YARA-X runtime state

The embedded Hybrid Agent now configures its Agent state environment before any transitive imports of capability and content-security modules.

Previously, the persistent Hybrid worker could import the YARA-X modules while they still pointed at the standalone Agent default:

```
/var/lib/capivara-agent
```

even though the real managed YARA-X engine and rules were stored under:

```
/opt/dsm/runtime/hybrid-agent-state
```

This caused Universal Content retries to report:

```
security_scan_failed
YARA-X engine is unavailable
```

while a fresh CLI process under the same `capivara` user reported the engine and ruleset as ready.

## Managed YARA-X permissions

Linux managed YARA-X metadata is now published with an explicit runtime-readable permission contract:

- engine `current.json`: 0644
- managed `yr` binary: 0755
- ruleset `current.json`: 0644
- managed baseline rules: 0644

This fixes installations performed through `sudo cap agent security yara ... install`, where `tempfile.mkstemp()` could leave root-owned pointer files as 0600 and inaccessible to the Hybrid runtime user.

## Validation

The fix passed the project gates for PR #639, including:

- CI Gate
- Phase 22 final end-to-end gate
- YARA-X Security Management
- External Controller Agent E2E
- M10 Final E2E Release Validation
- Final Customer Distributed E2E
- Agent Instance Runtime
- PostgreSQL Baseline v2 Isolated Deployment
- Customer Workspace Functional Deployment
- Capivara 2.0 Release Readiness
- Baseline Update Reconciliation

## Included changes

- PR #639 — Hybrid YARA-X managed-state permissions and early Hybrid runtime environment initialization.

## Operational recovery

After v2.0.74 is published, a Hybrid Controller affected by the stale `YARA-X engine is unavailable` content state should upgrade normally:

```bash
sudo cap update run
```

After the Dashboard worker restarts on v2.0.74, the next eligible Universal Content reconcile retries the pending security scan using the managed engine and rules from the Hybrid Agent state directory.
