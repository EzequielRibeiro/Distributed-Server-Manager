# Capivara DSM 2.0.123

## Minecraft Server Pack migration

- Integrates the hybrid Agent Server Pack migration flow from the customer dashboard (PR #916).
- Preserves staged runtime directory access policy, file ownership and ACLs during migration (PR #917).
- Applies attested Server Pack configuration and KubeJS overrides and handles failed service state before rollback (PR #917).

## Validation and operational safeguards

- PR #917 GitHub Actions checks passed; isolated migration and Controller/PostgreSQL integration were exercised.
- Publication is disabled in this preparation branch pending full release readiness and explicit publication approval.
- Deploying DSM may stop active managed game instances temporarily; do not run `cap update run` on horizon-server without a separate maintenance authorization.
- No automatic Minecraft 005 Server Pack migration is authorized.
