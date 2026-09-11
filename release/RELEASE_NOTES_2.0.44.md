# Capivara DSM 2.0.44

Patch release that hardens the GitHub release publisher after the post-publication validation introduced around Capivara DSM 2.0.43 exposed two publication-boundary defects.

## Why 2.0.44 exists

The public assets originally published for `v2.0.43` were generated from commit `4bd802ee2457f9c5fe32f836b04b7c42e96a3fbe` and carried that commit in their manifests. PR #430 then moved the public-asset smoke validation inside the release publisher because GitHub Actions events created with the repository `GITHUB_TOKEN` do not recursively trigger a second workflow from the generated release event.

Merging #430 also exposed a separate publisher-idempotency defect. At that time `.github/workflows/release.yml` itself was one of the paths that triggered the branch release workflow. The merge therefore re-entered the already-published 2.0.43 release path and the old publisher force-moved `v2.0.43` to the #430 merge commit while retaining the previously published assets. The new public smoke correctly failed because the tag commit and the manifests no longer matched.

The 2.0.43 historical tag/asset mismatch is not hidden or normalized by this release. Version 2.0.44 supersedes it as the first patch intended to exercise the corrected immutable publication path end to end.

## Idempotent and immutable publisher

PR #431 changes the publication contract so that:

- only a change to `release/RELEASE_TRIGGER` may start the branch publisher;
- editing the release workflow, readiness metadata or release notes does not republish the current version;
- canonical release tags are never force-moved;
- an existing canonical tag must resolve to the current approved release commit or publication fails closed;
- existing standalone Linux and Windows Agent release tags must resolve to the same approved commit before they can be reused;
- an existing GitHub Release keeps its assets unchanged and may be reused only when the tag identity matches the approved release commit;
- the canonical public release is downloaded and validated after publication by `tests/published_release_smoke_test.py`;
- the readiness regression rejects reintroduction of force-retagging or broad workflow-maintenance publication triggers.

The intended 2.0.44 publication proof is therefore:

`explicit RELEASE_TRIGGER -> immutable canonical/Agent tags -> public GitHub Release -> download public assets -> checksums/manifests/commit/file-count/path-safety -> standalone Agent parity`

## Validation before publication

PR #431 completed successfully with:

- CI, including Bash/PowerShell/Python/JavaScript validation;
- real Linux installation smoke;
- updater and CLI regressions;
- Catalog v2;
- reproducible release build;
- Linux and Windows Agent package tests;
- Phase 22 final end-to-end gate;
- Final Customer Distributed E2E;
- Capivara 2.0 Release Readiness;
- P0-D Structured Placement;
- P10 Agent Network and Port Pool;
- Published Release Smoke pull-request preflight;
- administrative, observability, semantic and legacy audit gates.

After #431 merged, its change to `.github/workflows/release.yml` did **not** trigger the Release workflow, proving that workflow maintenance no longer republishes the current version.

## Release scope

This patch contains no database migration and no game-runtime feature change. It changes only the release publication boundary and version metadata.

It includes:

- #430 — validate the public GitHub Release inline in the publisher;
- #431 — make release triggers, tags and existing release reuse idempotent and fail-closed.

## Operational boundary

Publishing 2.0.44 does not update an active Controller or Agent installation. Rollout to `horizon-server` or any `/opt/dsm` installation remains a separate operator-approved action after the public release validation succeeds.
