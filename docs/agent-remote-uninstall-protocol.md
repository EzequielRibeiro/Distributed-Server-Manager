# Remote Agent uninstall protocol

The remote uninstall path is deliberately two-phase so the Controller does not destroy the Agent registration before the host has acknowledged a typed uninstall request.

1. An administrator requests `preserve-data` or `purge` and confirms the exact Agent ID.
2. The Controller persists an `AgentUninstallCommand` in `queued` state.
3. The next authenticated heartbeat delivers `phase=prepare`. No shell text is supplied by the Controller.
4. The Windows Agent validates the schema/action/phase/mode, persists the request locally and reports `accepted` on the next heartbeat.
5. Only after the Controller persists that acceptance does a later heartbeat return the same typed command with `phase=commit`.
6. The Agent copies the packaged `uninstall-agent.ps1` outside `InstallRoot`, launches the temporary copy detached, reports/records `committed`, and exits so the runtime files are no longer held open. `-Purge` is added only for an explicit purge request.
7. The Controller keeps the logical Agent record while decommissioning. Final logical removal remains a separate administrative step after host shutdown/offline observation.

The authenticated heartbeat accepts only permanent Agent credentials before uninstall state or commands are exchanged.

## Windows runtime integration

`service/run-agent.ps1` prefers `runtime/agent_entrypoint.py` when that packaged runtime file exists. The entrypoint wraps the existing `agent.py` runtime rather than introducing a second implementation: it adds the local `uninstall_result` to heartbeat inventory and consumes only typed uninstall commands returned by the Controller.

## Safety

- exact Agent-ID confirmation is required;
- `purge` is blocked while the Controller still has registered instances for the Node;
- `preserve-data` may remove the runtime while preserving `instances` and `backups`;
- command kind must be `AgentUninstallCommand` schema version 1;
- action must be `uninstall-agent`;
- phase must be `prepare` or `commit`;
- mode must be `preserve-data` or `purge`;
- no command line, executable path, script body, browser path, or arbitrary PowerShell fragment is accepted from the Controller.

Controller-side forced deregistration remains a separate recovery operation for a host that is already dead or unreachable.
