# Windows SteamCMD bootstrap retry

Observed on Node2 during the v2.0.17 E2E validation: the first `steamcmd.exe +quit` invocation can self-update and terminate with exit code 7 even though the bootstrap succeeds. The Windows Agent now retries the functional probe up to three times and still requires a later exit code 0 before promoting the staged SteamCMD directory into the managed tools path.

This preserves strict validation while tolerating the SteamCMD first-run bootstrap/relaunch behavior.
