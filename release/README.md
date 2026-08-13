# Capivara DSM releases

The project version has a single source of truth: the root `version` file.

Build a release from the current commit:

```bash
release/build_release.sh HEAD dist
```

The build creates three files:

- `capivara-dsm-X.Y.Z.tar.gz`: reproducible installation package;
- `capivara-dsm-X.Y.Z.tar.gz.sha256`: archive integrity checksum;
- `capivara-dsm-X.Y.Z.manifest.json`: version, commit, timestamp and required files.

The package intentionally excludes logs, caches, runtime state, instances,
downloaded SteamCMD files and other machine-local data.

## Publishing

1. Update the root `version` file and related changelog.
2. Merge the validated change into `main`.
3. Create and push the matching tag, such as `v1.0.0`.

The Release workflow rejects a tag that differs from the root version, runs
the validation suite, builds the artifacts and publishes the GitHub Release.
Tags with a SemVer suffix, such as `v1.1.0-dev.1` or `v1.1.0-rc.1`, are
published as pre-releases and do not replace the latest stable release.

The updater accepts only a newer SemVer by default. An intentional reinstall
or rollback must use `--allow-same-version` or `--allow-downgrade`.
