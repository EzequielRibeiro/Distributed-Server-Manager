# DayZ native shutdown: missed transition during status polling

## Production evidence (2026-10-14, America/Sao_Paulo)

- Instance: `cli-000001-dayz-001`.
- Maintenance due: 09:32:24; expected shutdown: 09:33:10.
- Native DayZ process PID `3738932` stopped at 09:36:11 according to systemd.
- The unit started again at 09:36:19 with PID `224240`.
- Status command completed 09:35:46: `running`, PID `3738932`.
- Status command completed 09:36:56: `running`, PID `224240`.
- Maintenance marked `native_shutdown_timeout` at 09:37:15.
- A further status command completed 09:37:47, after the failure.
- `Restart=no` on the systemd unit. No `start` command appeared in `agent_instance_commands` for 09:30–09:40. **The initiator of the new start is not yet established.**

## Version reconciliation gate

The production file `/opt/dsm/dashboard/workers/maintenance_worker.py` has SHA-256
`53ce40a5d56adcc645da61c87bb0c48d33a03478b86ef0cc63304c8a119e0b3c`.
It differs from `main`. Production includes expected-shutdown scheduling and a
termination grace that the examined main version lacks. **Do not deploy a patch
based solely on main without reconciling the production changes.**

## Acceptance criteria

1. Preserve expected-shutdown deadline calculation and the 180s + 60s
   timeout semantics unless a separate change is justified.
2. Confirm the native stop occurred in the expected window using trusted
   lifecycle/systemd transition evidence; PID change alone is insufficient.
3. Do not treat an unrelated external restart as maintenance success.
4. Do not issue a duplicate stop or start when native restart already occurred.
5. Do not mark timeout while a completed, relevant stop observation is pending
   consumption; bound delayed probes and handle late results safely.
6. Keep true shutdown failures fail-closed and preserve instance persistence.
7. Add isolated regression tests for: normal native stop, stop+start between
   polls, unrelated restart, delayed status completion, and genuine timeout.

## Release gates

- No changes to live DayZ service, game files, or persistence during development.
- Run unit tests in an isolated checkout.
- Reconcile worker and test differences with production before PR/merge.
- Require explicit approval for production deployment.

## systemd evidence model and trust boundary (2026-10-14)

The Agent systemd adapter now exposes `InvocationID`,
`ActiveEnterTimestamp`, and `InactiveExitTimestamp` in the branch.
These fields identify the **current** invocation and its state transition;
they do not themselves attest to a completed stop of the prior invocation.
In particular, `NRestarts=0` and `Restart=no` do not identify who
initiated a subsequent `systemctl start`.

A safe, auditable solution requires the Agent to supply an authenticated,
instance-scoped lifecycle record containing the prior invocation identity,
the stop-completed event, the new invocation identity, timestamps and the
actor/reason for the start when available. The record must be bound to
the expected native maintenance cycle and obtained through the existing
authenticated Agent channel. A text field such as
`source=trusted-systemd-lifecycle` or a caller-provided boolean
`authenticated=True` is **not** sufficient to establish provenance.

The pure validator in `dashboard/workers/dayz_native_transition.py` is
a building block only; it is not wired into the worker and its
`authenticated` flag must never be populated from untrusted payloads.
The existing regression with a hard-coded `verified_transition` is a
desired-behavior specification, **not proof** that real lifecycle evidence
can currently be obtained.

Before deployment: design and test Agent-side event collection,
durability/retention, identity binding, event ordering and timestamp
normalization; integrate evidence retrieval into the worker; ensure
already-running instances skip unsafe offline-only work and duplicate
start commands; and investigate the external start initiator.
