# Capivara DSM 2.0.43

Patch release following Capivara DSM 2.0.42 to correct the generated DSM release manifest and add a post-publication proof of the artifacts that operators and Agents actually receive from GitHub Releases.

## DSM release manifest file count

The first post-publication smoke validation against `v2.0.42` found that its DSM manifest declared `file_count=1759` while the published archive contained 1758 regular files.

The archive checksum and payload were not changed by this discovery; the inconsistency was in the generated `file_count` metadata. The root cause was a historical repository-root `release-manifest.json` from Capivara DSM 1.4.3. `release/build_release.sh` stages tracked source files, counted that stale manifest, then generated the release-specific manifest while applying the intended `+1` for the newly generated file. Because a manifest was already present in staging, the final count was one too high.

This release:

- removes the historical repository-root `release-manifest.json` from source control;
- keeps `release-manifest.json` as a release-generated artifact inside the package;
- requires `tests/release_build_test.sh` to compare the manifest `file_count` with the actual number of regular files in the generated package;
- preserves deterministic/reproducible release packaging.

## Published Release Smoke

A new `Published Release Smoke` validates the public GitHub Release after publication instead of trusting only artifacts built inside CI.

For a canonical `v<SemVer>` release, the smoke test downloads and validates the nine required DSM/Linux/Windows assets:

- archive/ZIP;
- SHA-256 checksum;
- external manifest.

The validator verifies:

- canonical tag and SemVer metadata;
- exact release commit identity;
- stable/prerelease classification;
- presence and non-empty state of every required public asset;
- published SHA-256 checksums;
- external manifest identity with the manifest packaged inside each archive;
- DSM required files, version and exact file-count parity;
- Linux/Windows Agent required files, per-file size and SHA-256 declarations, version and channel;
- archive path safety;
- standalone `agent-linux-v<version>` and `agent-windows-v<version>` releases point to the same commit and publish byte-identical Agent artifacts as the canonical release.

Intermediate standalone Agent release publication events are intentionally ignored by the canonical smoke. The live proof runs after the canonical `v<SemVer>` GitHub Release exists, and it can also be invoked manually for a chosen canonical tag.

## Validation

The publication-boundary changes were validated through PR #428 with successful:

- CI, including real Linux installation smoke, updater regressions, Catalog v2, reproducible release build, Linux/Windows Agent packages and Phase 22 final E2E;
- Update Manager Regression;
- Published Release Smoke pull-request preflight, including manifest/file-count parity;
- Final Customer Distributed E2E;
- P0-D Structured Placement;
- Capivara 2.0 Release Readiness;
- P10 Agent Network and Port Pool;
- administrative/semantic/legacy audit and observability gates.

After this release is published, the new live `Published Release Smoke` must validate the actual `v2.0.43` GitHub assets. That post-publication check is intentionally separate from the pre-release readiness contract.

## Release scope

This patch contains no database migration and no game-runtime feature change. It changes the release artifact contract and its validation boundary only.

It includes:

- #428 — validate published GitHub release artifacts and correct generated DSM manifest file-count parity.

## Operational boundary

This release publication does not itself update an active Controller or Agent installation. Rollout to `horizon-server` or any `/opt/dsm` installation remains a separate operator-approved step after the public release smoke succeeds.
