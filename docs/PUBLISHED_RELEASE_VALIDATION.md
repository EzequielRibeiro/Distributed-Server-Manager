# Published Release Validation

This document defines the publication boundary for Capivara DSM releases.

## Why this gate exists

The normal CI and Update Manager regressions validate artifacts generated inside the repository workflow. The release workflow then uploads a different operational object: the public GitHub Release consumed by operators and Agent update discovery.

A successful build therefore is not sufficient evidence that the public release is complete and internally consistent. `Published Release Smoke` validates the assets after GitHub has published them.

## Automatic boundary

The canonical publisher in `.github/workflows/release.yml` runs `tests/published_release_smoke_test.py` immediately **after** the canonical GitHub Release has been created or confirmed. This is the authoritative automatic path because releases created by a workflow with `GITHUB_TOKEN` do not recursively start another workflow from the resulting `release` event.

`.github/workflows/published-release-smoke.yml` remains available for canonical `v<SemVer>` release events created outside that `GITHUB_TOKEN` publication path and for explicit manual validation. The intermediate `agent-linux-v<version>` and `agent-windows-v<version>` publication events are intentionally ignored because the canonical release does not exist yet at that point.

Pull requests that change the publication validator compile it and execute the local release-builder regression, including manifest/file-count parity. They do not reinterpret or weaken an already-published release merely to make the pull request green. The public transport proof is produced only by validating the real canonical release after publication, either inline in the publisher or by an explicit release/manual validation run.

`tests/release_readiness_test.py` protects this ordering contract: both canonical publication paths in `release.yml` must invoke the public validator only after their GitHub Release publication step.

## Required canonical assets

For version `<version>`, the canonical `v<version>` release must contain all nine operational artifacts:

- `capivara-dsm-<version>.tar.gz`
- `capivara-dsm-<version>.tar.gz.sha256`
- `capivara-dsm-<version>.manifest.json`
- `capivara-agent-linux-<version>.tar.gz`
- `capivara-agent-linux-<version>.tar.gz.sha256`
- `capivara-agent-linux-<version>.manifest.json`
- `capivara-agent-windows-<version>.zip`
- `capivara-agent-windows-<version>.zip.sha256`
- `capivara-agent-windows-<version>.manifest.json`

Additional release assets such as signatures are allowed, but the required set may not be incomplete.

## What is verified

`tests/published_release_smoke_test.py` downloads the assets from the public GitHub Release and fails closed unless all of the following hold:

1. The canonical tag is a `v<SemVer>` tag and resolves to one concrete commit.
2. Stable/prerelease metadata agrees with the version.
3. Every required public asset exists and is non-empty.
4. Every archive matches its published `.sha256` file.
5. DSM, Linux Agent and Windows Agent manifests report the release version and the exact commit referenced by the canonical tag.
6. The external manifest is identical to the manifest packaged inside the corresponding archive.
7. The DSM archive contains the manifest-declared required files, the correct `version`, and a file count consistent with the manifest.
8. Linux and Windows Agent archives contain every manifest-declared file, with the exact declared size and SHA-256 digest, and the correct `VERSION`.
9. Archive member names remain inside the expected package root and do not contain path traversal.
10. The standalone Linux and Windows Agent release tags resolve to the same commit as the canonical release, contain their required three assets, and publish byte-identical copies of the corresponding canonical Agent artifacts.

The validation reads published artifacts only. It does not install the package, modify an active Controller/Agent, write under `/opt/dsm`, or alter game instances.

## Generated manifest boundary

The repository root must not carry a historical `release-manifest.json` as a source file. `release/build_release.sh` generates that manifest inside the staged package for the exact release commit. `tests/release_build_test.sh` verifies that its declared `file_count` equals the number of regular files actually packaged, preventing a stale source manifest from shifting the count.

## Relationship to rollout

Passing this gate means the public release transport boundary is valid. It does **not** prove that an existing production or test host has been upgraded successfully.

A host rollout remains a separate, operator-approved operation. Before any active installation is mutated, the operator should confirm the target release and current host health, preserve the applicable backup/recovery boundary, execute the supported updater, and then validate Controller/Agent health and representative runtime lifecycle behavior on that host.

For the Capivara test environment, changes to `/opt/dsm` remain outside this automated gate and require explicit approval before execution.
