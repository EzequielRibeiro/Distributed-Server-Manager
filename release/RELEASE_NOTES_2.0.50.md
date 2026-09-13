# Capivara DSM 2.0.50

Hotfix release for Dashboard Automation Worker database parity on Controller/Hybrid nodes.

## Automation Worker database backend

- load the configured `DSM_DATABASE_*` values from `config/dsm.conf` before creating the Automation Worker backend;
- preserve explicit service environment values over file configuration;
- import only the database allowlist and ignore unrelated configuration keys;
- prevent silent fallback to local SQLite when the Controller is configured for PostgreSQL or MySQL/MariaDB.

## Lifecycle conflict HTTP contract

- preserve structured JSON emitted by API scripts that exit non-zero;
- keep lifecycle conflict fields such as `error`, `command_id`, `requested_action` and `active_action`;
- map contradictory in-flight lifecycle requests to HTTP `409 Conflict` instead of wrapping the structured error and returning `422`;
- preserve legacy plain-text subprocess error handling for scripts that do not emit JSON.

Live validation on `horizon-server` proved that duplicate `restart` requests reuse the same command id and a concurrent contradictory `stop` is rejected with HTTP 409 while the original restart continues.

## Incident fixed

After the v2.0.49 rollout on `horizon-server`, `automation_worker.py` initialized the local SQLite database because the worker service exported `DSM_ROOT` but not the database variables. During Baseline v8 startup this produced a transient `sqlite3.IntegrityError: UNIQUE constraint failed: baseline_upgrades.version` and restarted the worker group.

The Hybrid Agent and Customer Workspace workers already read the configured database environment. This release brings the Automation Worker to the same contract.

## Validation

- Automation Worker tests pass, including PostgreSQL configuration loading, allowlisted keys, and explicit environment precedence;
- Hybrid worker environment contract remains valid;
- Baseline/update regression suite passes;
- reproducible release build passes;
- full PR CI, isolated PostgreSQL, functional deployment, runtime and Final Customer Distributed E2E gates pass.

This release includes all fixes from v2.0.49, including Baseline Upgrade v8 and the legacy v2.0.46 updater bridge.
