# Capivara DSM 2.0.69

Patch release focused on authenticated Steam Workshop reconciliation on Hybrid nodes.

## Highlights

- Hybrid workers now receive the configured Steam account name through `DSM_STEAM_USER`.
- The Steam account is read from `config/providers/steam.conf` without sourcing or evaluating the file.
- Only the account name is imported; passwords and Steam Guard secrets are never loaded or persisted.
- Invalid shell syntax or unsafe account values fail closed.
- The account is exported before Hybrid child workers start, allowing them to reuse SteamCMD credentials cached for the `capivara` user under the Hybrid home.

## Included changes

- PR #611 — propagate the configured Steam account to the Hybrid worker environment.

## Operational impact

This completes the authenticated DayZ Workshop flow introduced in 2.0.68. On a Hybrid node, after SteamCMD is authenticated under the `capivara` execution context, managed Workshop reconciliation can now resolve the configured Steam account and reuse that cached session.

## Compatibility and upgrade notes

- Patch release after 2.0.68.
- No database migration.
- No Steam password is stored by Capivara.
- Existing Workshop cache, revision validation and security scanning remain fail-closed.
- Release preparation itself does not mutate an active installation.
