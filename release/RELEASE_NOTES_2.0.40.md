# Capivara DSM 2.0.40

Patch release following Capivara DSM 2.0.39 to close a managed-firewall compatibility regression reproduced during the real Palworld rollout on `horizon-server`.

## Hybrid managed firewall compatibility

- Recover canonical Catalog network exposure when an older Hybrid RuntimeSpec persists `catalog_runtime_policy.network_exposure` as an empty list.
- Treat empty exposure as recoverable legacy state only in Hybrid mode, where the canonical local Catalog is available.
- Preserve explicit empty exposure for non-Hybrid Agents; no port is made public merely because it is reserved.
- Preserve fail-closed behavior when the Catalog runtime definition, network contract, port role, protocol, or resolved binding is invalid or unavailable.
- Keep firewall ownership scoped to the instance and continue reconciling only explicitly public Catalog roles.

For `palworld.stable`, the canonical exposure remains:

- `game=24010/udp` -> `public`
- `rcon=24011/tcp` -> `none`
- `rest_api=24012/tcp` -> `none`

The regression reproduced on the real Hybrid host with Palworld healthy and listening on UDP 24010 while UFW was active with default incoming deny, but the privileged firewall request contained `"rules": []`. The persisted RuntimeSpec contained `"network_exposure": []`, preventing the existing missing-policy fallback from consulting the local Catalog.

After this fix, the same legacy Hybrid state resolves exactly one managed firewall rule for the public game port and does not expose RCON or REST API.

## Regression coverage

- Add a Palworld-specific Hybrid regression reproducing `network_exposure: []` with resolved ports 24010/24011/24012.
- Assert that only `game=24010/udp` becomes a public firewall rule.
- Assert that `rcon` and `rest_api` remain non-public.
- Assert that non-Hybrid Agents preserve an explicit empty exposure list as zero public rules.
- Existing managed-firewall, lifecycle, ownership, fail-closed, Linux/Hybrid, P10 and distributed E2E suites remain green.

## Validation

Validated through PR #419 with successful:

- CI;
- Agent Instance Runtime;
- P10 Agent Network and Port Pool;
- Capivara 2.0 Release Readiness;
- Final Customer Distributed E2E;
- External Controller Agent E2E;
- supporting audit, observability and customer gates.

## Release scope

This release contains the firewall compatibility fix merged through:

- #419 — recover empty Hybrid firewall exposure.
