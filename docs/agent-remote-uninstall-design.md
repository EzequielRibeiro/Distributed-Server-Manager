# Remote Agent uninstall sequencing

Controller-side removal and host-side uninstall are deliberately separate operations.

For a remote uninstall flow, the Controller must not delete the Agent registration before the host has received and acknowledged the uninstall command. Otherwise the credential/channel used by heartbeat is lost before the host can execute cleanup.

Required sequence:

1. Admin requests host uninstall with exact Agent ID confirmation and an explicit mode (`preserve-data` or `purge`).
2. Controller persists an uninstall request while keeping the Agent registration and credential valid.
3. Agent receives a typed uninstall command through the existing heartbeat command channel. No arbitrary shell command is accepted.
4. Agent validates the command, launches the platform uninstall helper detached from the long-running Agent process, and returns an acknowledgement/result state where possible.
5. Controller marks the host uninstall request delivered/acknowledged.
6. Only after acknowledgement (or an explicit admin override for an unreachable/dead host) may Controller registration removal proceed.
7. `purge` remains destructive and must require an additional explicit confirmation.

The existing `/api/admin/agent/remove` endpoint remains Controller-registration removal only until this sequence is implemented end-to-end.
