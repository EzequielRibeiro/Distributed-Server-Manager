# Validation focus for 2.0.18

Primary E2E regression target: Windows Agent SteamCMD self-install on a clean host where the first SteamCMD bootstrap invocation returns exit code 7 after self-update/relaunch. The Agent must retry the probe and only complete installation after a subsequent exit code 0.
