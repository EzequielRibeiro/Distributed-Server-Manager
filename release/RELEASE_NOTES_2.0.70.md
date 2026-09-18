# Capivara DSM 2.0.70

Patch release focused on Steam authentication consistency for Linux Agents.

## Highlights

- `cap steam auth` now authenticates in the same OS user, HOME and SteamCMD context used by the Agent runtime.
- Hybrid nodes use the actual `dsm-dashboard-worker.service` runtime user with `HOME=/opt/dsm`.
- Standalone Linux Agents use the `capivara-agent.service` runtime context.
- SteamCMD is resolved through the Agent runtime's canonical `_steamcmd()` implementation instead of the legacy `/opt/dsm/tools/steamcmd` path.
- Steam provider configuration is treated as data; it is no longer sourced as shell by `cap steam auth`.
- Passwords and Steam Guard secrets remain handled only by SteamCMD and are never stored by Capivara.

## Included changes

- PR #613 — authenticate Steam in Agent runtime context.

## Operational impact

This completes the authenticated Steam Workshop flow for Linux Agent and Hybrid modes. After upgrade, administrators can run:

```bash
sudo cap steam auth
```

and the command will create the Steam session in the same runtime context later used for unattended Workshop reconciliation.

No database migration is required.
