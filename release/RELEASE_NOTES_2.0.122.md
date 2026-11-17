# Capivara DSM 2.0.122

## Agent maintenance transaction safety

- Validates that maintenance checkpoints still target the registered installation before commit or rollback (PR #913).
- Rejects missing, moved, or foreign-owned Agent installations and inconsistent affected-instance bindings.
- Normalizes Agent identity failures to the maintenance transaction error contract.

## Validation

- PR #913: 24 GitHub CI checks successful; 5 focused regression tests passed on node1 against merged main.
- Release candidate requires full readiness and packaging validation before publication.
