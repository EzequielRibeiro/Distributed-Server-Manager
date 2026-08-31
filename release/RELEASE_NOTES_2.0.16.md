# Capivara DSM 2.0.16

## Release focus

This release finalizes the Windows Agent 2.0.16 candidate and includes the SteamCMD self-install fix validated from the Node2 failure scenario.

## Windows Agent installation and bootstrap

- Removes fragile `python -c` usage from Windows remote installation paths and preserves UTF-8 package validation/local identity generation.
- Resolves `latest` to a concrete stable Agent release before remote bootstrap.
- Requires explicit Windows bootstrap success verification and validates the installed runtime, identity and Scheduled Task.
- Keeps Pairing Tokens out of SSH argv and administrator-facing error messages.

## SteamCMD self-install

- Fixes `install-steamcmd` jobs incorrectly entering game-data validation and failing with `invalid game`.
- Handles `install-steamcmd` before any game-specific selection validation.
- Installs SteamCMD in `C:\ProgramData\CapivaraAgent\tools\steamcmd`.
- Performs a functional `steamcmd.exe +quit` probe before promoting the installation.
- Makes installation idempotent when a functional managed SteamCMD already exists.
- Detects SteamCMD through PATH, `STEAMCMD_PATH`, or the managed Agent path.
- Publishes `steamcmd=true` after successful managed installation.
- Hardens ZIP member validation against Windows path traversal using backslashes.

## Windows observability

- Publishes host and Agent-process telemetry for CPU, RAM, disk, network and uptime.
- Includes disk throughput/IOPS and Processor Queue Length where available.
- Preserves distributed Storage Pool telemetry and Windows default Storage Pool creation.

## Regression coverage

- Adds coverage for `install-steamcmd` jobs without `selection.game`.
- Adds managed SteamCMD capability detection coverage.
- Adds Windows ZIP traversal validation coverage.

## Compatibility

- Controller and Agent release version: 2.0.16
- Linux Agent package: `capivara-agent-linux-2.0.16.tar.gz`
- Windows Agent package: `capivara-agent-windows-2.0.16.zip`

## Final E2E validation target

On Node2 Windows without SteamCMD:

Dashboard -> `Tentar novamente` -> `install-steamcmd` -> managed installation -> job `completed` -> heartbeat/capability `steamcmd=true` -> SteamCMD alert clears.
