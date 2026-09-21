# Capivara DSM 2.0.106

Controller content-provider configuration release.

## Highlights

- Adds **System → Content Providers** administration in the Controller.
- CurseForge API key can be saved, tested and removed from the UI.
- GitHub Releases supports an optional managed Personal Access Token.
- Modrinth connectivity can be tested without credentials.
- Steam / Steam Workshop shows the configured Steam user and keeps password / Steam Guard handling on SteamCMD.
- Provider credentials are stored under `config/providers` with restricted permissions and are never returned by the administrative API.
- CurseForge provider errors now surface controlled messages for authorization, rate limiting and connectivity failures.
- Customer content search no longer shows a false “no compatible content” state when the provider request actually failed.
- Minecraft CurseForge resolution automatically uses the Controller-managed credential.
- GitHub provider automatically uses the Controller-managed token when no explicit environment token is set.

## Validation

PR #748 passed the complete validation set, including CI, Universal Content Platform, Universal Content E2E, Generic Content Providers, M9 Minecraft Modpacks, M10 Final E2E Release Validation, Release Readiness, and PostgreSQL/MySQL/MariaDB baseline gates.
