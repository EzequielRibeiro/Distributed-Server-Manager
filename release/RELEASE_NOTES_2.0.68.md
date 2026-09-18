# Capivara DSM 2.0.68

Patch release focused on Steam Workshop authentication and error reporting.

## Highlights

- DayZ Workshop content now inherits the authenticated Steam requirement from the runtime catalog.
- Project Zomboid Workshop authentication is explicitly declared as anonymous.
- Customer-supplied Workshop authentication is ignored; the Controller owns this policy through the RuntimeDefinition.
- Linux and Windows Agents now detect SteamCMD Workshop failures reported in stdout even when SteamCMD exits with code 0.
- The real SteamCMD failure reason is surfaced instead of being misclassified as a missing managed cache.

## Included changes

- PR #609 — enforce runtime-owned Workshop authentication and detect zero-exit SteamCMD failures.

## Operational impact

This addresses the production case where DayZ Workshop reconciliation executed:

`+login anonymous +workshop_download_item 221100 1828439124 validate`

and SteamCMD returned:

`ERROR! Download item 1828439124 failed (Failure)`

while still exiting with status 0.

After upgrading to 2.0.68, DayZ Workshop reconciliation will request the Agent's authenticated Steam identity and will fail with the actual SteamCMD reason when SteamCMD reports an application-level failure.

## Compatibility and upgrade notes

- Patch release after 2.0.67.
- No database migration.
- Controller/Hybrid and Agents should be upgraded together so the Controller persists the runtime-owned Workshop auth policy and Agents use the improved failure parser.
- Existing cache revision validation and security scanning remain fail-closed.
- Release preparation itself does not mutate an active installation.
