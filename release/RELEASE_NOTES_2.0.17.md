# Capivara DSM 2.0.17

## Release focus

This patch release republishes the Windows Agent with the SteamCMD self-install corrections that were merged after the original 2.0.16 release assets were already published.

## Why 2.0.17

The 2.0.16 tag and release assets were created before the final SteamCMD fixes reached `main`. Reusing or silently replacing the 2.0.16 Windows ZIP would break release traceability, checksum stability and updater reproducibility. Version 2.0.17 establishes a new immutable release boundary for the corrected code.

## Windows Agent / SteamCMD

- Handles `install-steamcmd` before game-specific validation, preventing the `invalid game` failure seen on Node2.
- Installs managed SteamCMD under `C:\ProgramData\CapivaraAgent\tools\steamcmd`.
- Validates the installed executable with a functional `steamcmd.exe +quit` probe.
- Keeps installation idempotent when a working managed SteamCMD already exists.
- Detects SteamCMD from PATH, `STEAMCMD_PATH`, or the managed Agent path.
- Publishes the SteamCMD capability after successful installation so Controller alerts can clear.
- Preserves Windows ZIP path traversal hardening.

## Release artifact pipeline

- Adds a dedicated reproducible Windows Agent artifact workflow for `main`.
- Verifies the generated ZIP, checksum and manifest before upload.
- Runs checksum verification from the correct `dist/` directory so the generated basename reference resolves correctly.
- Produces a downloadable CI artifact for pre-release Node2 validation.

## Compatibility

- Controller and Agent release version: 2.0.17
- Linux Agent package: `capivara-agent-linux-2.0.17.tar.gz`
- Windows Agent package: `capivara-agent-windows-2.0.17.zip`

## Final validation target

On Node2 Windows without SteamCMD:

Dashboard -> `Tentar novamente` -> `install-steamcmd` -> managed installation -> job `completed` -> heartbeat/capability `steamcmd=true` -> SteamCMD alert clears.

The release should not be considered operationally closed until that real Node2 E2E path succeeds with the 2.0.17 package.
