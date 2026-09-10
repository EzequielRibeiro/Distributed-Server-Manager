# Capivara DSM 2.0.37

Patch release following Capivara DSM 2.0.36 to complete managed firewall reconciliation for existing Hybrid instances.

## Hybrid managed firewall lifecycle

- Reconcile managed firewall rules before `start` and `restart`.
- Fail closed when firewall reconciliation fails; the game runtime is not started.
- Keep `stop` semantics unchanged; firewall cleanup remains tied to instance removal.
- Use the Hybrid privileged firewall unit automatically for embedded Hybrid Agents.
- Recover `network_exposure` from the canonical local Catalog v2 for RuntimeSpecs created before managed firewall exposure was persisted.
- Preserve persisted `network_exposure` as authoritative for newly materialized RuntimeSpecs.

## Compatibility

This release fixes the real upgrade scenario observed on an existing DayZ Hybrid instance whose RuntimeSpec contained resolved ports but predated persisted `network_exposure`.

The compatibility path uses the current local Catalog only when the persisted RuntimeSpec lacks exposure information.

## Validation

The regression suite covers:

- legacy DayZ RuntimeSpec using UDP 24000, 24002 and 24003;
- Catalog exposure recovery;
- firewall reconciliation before runtime start;
- fail-closed behavior;
- unchanged stop semantics;
- managed firewall lifecycle integration.

## Release scope

This release contains the lifecycle compatibility fix merged through:

- #413 — reconcile managed firewall on Hybrid lifecycle start.
