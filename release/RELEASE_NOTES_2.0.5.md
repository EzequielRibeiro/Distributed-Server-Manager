# Capivara DSM 2.0.5

## Linux Agent prerequisites

- Installs the SteamCMD 32-bit compatibility runtime during new Agent installation.
- Supports dependency preparation on Debian/Ubuntu, Fedora/RHEL/CentOS and openSUSE.
- Reports missing SteamCMD, Java, container and Wine runtimes as structured capabilities.
- Adds explicit Agent Doctor findings when an installed SteamCMD cannot run.
- Keeps optional heavyweight runtimes visible without installing them silently.

## Dashboard

- Displays the heartbeat-reported Agent version consistently.
- Shows a human-readable SteamCMD prerequisite failure with expandable technical details.
