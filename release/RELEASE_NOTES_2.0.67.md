# Capivara DSM 2.0.67

Patch release focused on Linux Steam Workshop cache discovery reliability.

## Highlights

- Linux Agents now recognize additional SteamCMD Workshop cache layouts used by distro/system SteamCMD installations, including user-scoped `~/.steam/steamcmd` roots.
- Cache discovery also includes the Agent-managed SteamCMD state root and the legacy DSM SteamCMD root.
- Discovery remains bounded to explicit approved roots; there is no filesystem-wide scan.
- Revision-aware reconciliation continues to validate `appworkshop_<AppID>.acf` before creating a managed revision snapshot.
- If an earlier cache candidate exists but contains a stale/mismatched revision, the Agent continues to later candidates and accepts only an exact revision match.
- Fail-closed behavior is preserved when no matching cache is found.

## Included changes

- PR #607 — detect distro/system SteamCMD Workshop cache roots and skip stale earlier candidates.

## Operational impact

This addresses the reconciliation failure:

`SteamCMD completed but the Workshop item was not found in a managed Steam cache`

when SteamCMD successfully downloads a Workshop item but stores it outside the previously known cache roots.

## Compatibility and upgrade notes

- This is a patch release after 2.0.66.
- No database migration is introduced.
- Linux Agents should be upgraded to 2.0.67 to receive the Workshop cache-discovery fix.
- Controller and Windows Agent artifacts are published from the same approved release commit for version parity.
- Existing revision verification and security scanning behavior remain unchanged.
- No direct changes are applied to an active `/opt/dsm` installation by release preparation itself; deployment continues through the normal Capivara updater.
