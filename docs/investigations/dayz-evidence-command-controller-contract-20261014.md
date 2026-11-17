# DayZ lifecycle evidence command: Controller contract

## Confirmed incompatibility

`database/agent_instance_runtime_repository.py` has an explicit `VALID_ACTIONS` set that does not include `systemd_lifecycle_evidence`. Its `enqueue()` writes only eight columns to `agent_instance_commands`, and `command_for_agent()` forwards only `command_id`, `agent_id`, `instance_id`, and `action`. The new Agent command requires `since` and `until`, so simply whitelisting the action would dispatch an invalid request.

## Proposed additive migration

1. Add nullable `parameters_json` (or equivalent) to `agent_instance_commands`, with a backwards-compatible migration for SQLite and PostgreSQL. Do not change existing action semantics.
2. Permit a strictly validated `parameters` object only for `systemd_lifecycle_evidence`. Require `since` and `until` as timezone-aware timestamps and enforce a maximum 900-second interval. Other actions must reject unexpected parameters.
3. Persist normalized parameters with the command atomically; `command_for_agent()` must include the validated `since` and `until` at top level for this action, matching `systemd_evidence_request.validate_evidence_request`.
4. Restrict who may enqueue evidence queries at the Controller API/worker boundary. Existing instance ownership checks are necessary but do not replace caller authorization.
5. Preserve command deduplication and result identity checks; ensure an evidence query never projects instance status or triggers lifecycle changes.
6. Add migration, SQLite/PostgreSQL repository, Agent dispatch, authorization, delivery, idempotency, and malformed-input regression tests before enabling the route.

## Trust boundary

The Agent reads the system journal; the Controller must authenticate the Agent transport and bind the returned command to the requested instance and interval. A journal stop/start pair is historical observation, not proof of native maintenance shutdown, not proof of who started the unit, and not permission to run offline-only maintenance. If a restart is already observed, fail closed or require operator intervention; do not issue a duplicate start.

## Release gate

Do not merge or deploy until the production worker divergence is reconciled, the false-timeout regression is resolved without unsafe offline work, the full Controller/Agent path passes tests, and live systemd journal field/ID compatibility is verified read-only.
