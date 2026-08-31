# Capivara DSM 2.0.18

## Windows Agent / SteamCMD

- Fixes the first-run SteamCMD bootstrap validation seen during the Node2 E2E test.
- `steamcmd.exe +quit` is now retried up to three times because the initial bootstrap can self-update/relaunch and return exit code 7 even when the update itself succeeds.
- The installer still requires a successful exit code 0 before promoting SteamCMD from staging into `C:\ProgramData\CapivaraAgent\tools\steamcmd`.
- Keeps the v2.0.17 fixes for system `install-steamcmd` jobs, managed-path detection, capability reporting and archive traversal hardening.

## Validation target

Node2 clean SteamCMD state -> Dashboard `Tentar novamente` -> download/bootstrap -> retry probe -> managed installation -> `steamcmd=true` -> alert clears.
