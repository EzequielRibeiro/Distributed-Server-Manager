# Capivara DSM 2.0.41

Patch release following Capivara DSM 2.0.40 to close the managed-firewall teardown regression reproduced during the real Palworld lifecycle validation on `horizon-server`.

## Managed firewall lifecycle teardown

- Reconcile managed firewall exposure to an empty desired rule set after an instance `stop` completes.
- Execute firewall teardown even when the runtime adapter reports an idempotent stop, allowing stale instance-owned rules to be recovered safely when the game is already stopped.
- Persist `desired_state=stopped` and the observed stopped state before privileged firewall teardown.
- Propagate privileged firewall teardown failures instead of reporting a fully successful lifecycle operation.
- Preserve the stopped desired state when firewall teardown fails so runtime reconciliation does not inadvertently restart the instance.
- Keep firewall ownership scoped to the instance; removing one instance's managed rules does not remove managed exposure belonging to other instances or unrelated UFW rules.

## Real Palworld regression

The regression was reproduced on the Hybrid test host after the 2.0.40 start-side firewall fix was validated successfully:

- Palworld started on `game=24010/udp` and Capivara created `capivara:cli-000001-palworld-001:game:udp:24010` in UFW;
- `cap instance stop cli-000001-palworld-001` correctly stopped the systemd runtime;
- `desired_state` and `observed_state` both became `stopped`;
- the Palworld process and UDP listener disappeared;
- the managed UFW rule for 24010 remained orphaned;
- the privileged firewall request/result still contained the start-side 24010 rule because lifecycle `stop` did not invoke the existing firewall removal path.

The privileged firewall bridge already supported instance-owned removal through an explicit `rules=[]` reconciliation. This release connects normal lifecycle stop to that teardown path.

## Regression coverage

- Require lifecycle stop to reconcile firewall rules to `[]` after the adapter stops.
- Verify teardown still runs when adapter stop is idempotent.
- Verify stopped desired/observed state is persisted before firewall teardown.
- Verify firewall teardown failure propagates while stored desired/observed state remains stopped.
- Preserve the existing full instance-removal ordering test.
- Replace the prior test expectation that stop must not touch managed firewall state, which encoded the behavior proven incorrect by the real host validation.

## Validation

Validated through PR #421 with successful:

- Agent Instance Runtime, including managed firewall lifecycle and general instance runtime suites;
- CI, including real Linux installation smoke, updater tests, Catalog v2, reproducible build, Linux/Windows Agent packages and Phase 22 E2E;
- P10 Agent Network and Port Pool;
- Capivara 2.0 Release Readiness;
- Final Customer Distributed E2E;
- External Controller Agent E2E on Linux and native Windows;
- supporting audit, observability, customer and Agent gates.

## Release scope

This release contains the lifecycle firewall teardown fix merged through:

- #421 — remove managed firewall exposure on instance stop.
