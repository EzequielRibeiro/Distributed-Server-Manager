# Capivara DSM 2.0.48

Hotfix release that makes the cap-only release line consumable by installations still running the v2.0.46 updater, while preserving a strictly cap-only installed product state.

## Legacy updater bridge

- add a release-package-only `bin/dsm` compatibility marker so the v2.0.46 verifier can validate the target archive before handing control to the target updater;
- keep the bridge non-executable and out of the release manifest required-files contract;
- never restore `dsm` as a supported or public CLI;
- keep `bin/dsm-compat` excluded from release artifacts.

## Cap-only installed state

- patch the target updater inside the release artifact to remove package-only `bin/dsm` and any retired `bin/dsm-compat` immediately after the staged tree is applied;
- make final installation validation require `bin/cap`, `core/bootstrap.sh` and the preserved configuration, not `bin/dsm`;
- fail closed if a retired internal CLI artifact remains after the update.

## Regression coverage

- reproduce the exact path-level contract enforced by the v2.0.46 release verifier;
- verify the compatibility marker exists only inside the published DSM archive and is not executable;
- verify checksums and internal/external release manifests remain coherent after the bridge is applied;
- validate the patched target updater with `bash -n` and assert that the source tree itself remains cap-only.

## Included runtime fixes

This release includes all changes from v2.0.47, including instance lifecycle arbitration, duplicate-command reuse, HTTP 409 lifecycle conflicts, Dashboard lifecycle gating, managed firewall/runtime hardening, and the broader cap-only/legacy cleanup.

There is no intentional database migration introduced specifically by this hotfix. The update still uses the normal preflight, backup, process guard, migration and rollback transaction.
