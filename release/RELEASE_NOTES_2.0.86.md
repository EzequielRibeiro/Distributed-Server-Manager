# Capivara DSM 2.0.86

Provisioning selector compatibility hotfix.

## Canonical runtime selectors

Fixes hybrid Agent provisioning for runtimes whose canonical selector contains version/build segments separated by `@`, for example:

- `1.21.1@21.1.251` (NeoForge)
- `1.20.1@0.16.14@1.0.1` (Fabric)

The Agent provisioning contract now validates selectors with a dedicated allowlist that includes `@` while continuing to reject spaces, slashes and shell-like characters.

## Provisioning failure persistence

Contract-validation failures are now written to the provisioning result file as a terminal failed result instead of allowing the executor process to exit before updating state. This prevents Customer instances from remaining indefinitely in `running/staged` at the beginning of provisioning.

## Validation

Adds regression coverage for compound selectors and for persisted contract-validation failures.
