# Remote Agent uninstall protocol

The remote uninstall path is deliberately two-phase so the Controller does not destroy the Agent registration before the host has acknowledged a typed uninstall request.

1. An administrator requests `preserve-data` or `purge` and confirms the exact Agent ID.
2. The Controller persists an `AgentUninstallCommand` in `queued` state.
3. The next authenticated heartbeat delivers the typed command. No shell text is supplied by the Controller.
4. The Windows Agent validates the schema/action/mode, persists the request locally and reports `accepted` on the next heartbeat.
5. Only after the Controller has persisted that acceptance may it return an uninstall commit for the same request ID.
6. The Agent launches the packaged `uninstall-agent.ps1` from a temporary copy outside `InstallRoot`, then exits. `purge` is only added for an explicit purge request.
7. The Controller keeps the logical Agent record while decommissioning. Final logical removal is a separate administrative step after host shutdown/offline observation.

`purge` is blocked while the Controller still has registered instances for the Node. `preserve-data` may remove the Agent runtime while preserving `instances` and `backups`.

This protocol intentionally avoids arbitrary remote command execution and avoids interpreting browser-provided paths or PowerShell fragments.
