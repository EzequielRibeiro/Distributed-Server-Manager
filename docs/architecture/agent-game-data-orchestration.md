# Agent-owned game-data orchestration

## Status

Modern recovery of the original PR #40 design on top of the current `main` architecture.

The Controller owns catalog resolution and the persistent command queue. The Agent owns execution and local game-data storage. No arbitrary shell command is sent by the Controller.

## Flow

```text
Dashboard / Controller API
        |
        | resolve RuntimeSelection
        v
agent_game_data_jobs
 queued -> delivered -> running -> completed/failed
        |
        | authenticated heartbeat
        v
Linux Agent / Hybrid Agent
        |
        | structured install/update/verify contract
        v
local game-data storage
```

## Controller

`AgentGameDataRepository` persists jobs using migration `025_agent_game_data_jobs.sql`. SQLite, MySQL/MariaDB and PostgreSQL variants use the same logical schema.

The HTTP contract is modular:

- `POST /api/agents/game-data` queues `install`, `update` or `verify`;
- `GET /api/agents/game-data/jobs?job_id=...` returns one job;
- `GET /api/agents/game-data/jobs?agent_id=...` lists recent jobs for an Agent;
- `/api/catalog/environment-install` remains a temporary compatibility alias for install requests.

Only administrators may queue or inspect these administrative jobs.

## Remote Linux Agent

The heartbeat delivers a resolved `RuntimeSelection`. `game_data_client.py` persists the request locally and starts `game_data_executor.py` outside the heartbeat process. Long installations therefore do not block liveness reporting.

The standalone executor supports Steam and HTTP/archive artifacts. Paths are constrained below the Agent game-data root, download checksums are validated when supplied, archive traversal is rejected and archive links are rejected.

The Linux Agent release package, installer and updater carry the game-data runtime together with the local `cap` CLI introduced by Agent Local Core.

## Hybrid

Hybrid nodes consume the same Controller queue. They execute through the full local installer, preserving provider behavior already available in a complete Capivara installation.

## Deliberate differences from PR #40

The recovery does **not** introduce `dashboard/server_part14.py` and does not change the systemd Dashboard entrypoint. The current `server_part13.py` delegates only the route transport to modular `agent_game_data_http.py` / `agent_game_data_api.py` modules.

The implementation also keeps the Agent Local Core package layout and adds native migration variants for SQLite, MySQL/MariaDB and PostgreSQL.

## Next phase

B3 exposes local observational surfaces using the Agent Local Core CLI:

```text
cap agent game-data list
cap agent game-data status <game>
cap agent jobs
```

Those commands must inspect Agent-local state and must not require a Controller database on a pure remote Agent.
