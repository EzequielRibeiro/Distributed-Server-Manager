# Controller Dashboard — Remote Agent Installation

## Status

Implemented on branch `feat/dashboard-remote-agent-install`, pending review/merge.

## Objective

Allow a Controller administrator to prepare and install a remote Capivara Agent from the **Agents** Dashboard while defining administrative settings before the Agent exists.

The initial preconfiguration contract includes:

- Controller;
- Region;
- Datacenter;
- administrative Agent name;
- managed TCP/UDP port range.

## Installation methods

The existing installation workflow remains available:

1. GitHub Release instruction;
2. local package instruction.

A third method is added for Linux:

3. **remote bootstrap via SSH from the Controller**.

SSH is used only for bootstrap. After enrollment, heartbeat and operations use the normal authenticated Controller-Agent protocol.

## SSH security contract

The Dashboard deliberately does **not** accept:

- SSH passwords;
- arbitrary private-key paths supplied by the browser.

The Controller service account must already have an OpenSSH identity/ssh-agent or another standard OpenSSH authentication configuration available locally.

The implementation preserves the existing `cap agent deploy` transport rules:

- no `shell=True`;
- structured SSH argv;
- `BatchMode=yes`;
- host-key verification is not disabled;
- remote sudo must work non-interactively;
- Linux/curl/bash/python3/sudo preflight runs before token issuance;
- existing Agent installation is detected and automatic reinstall is refused;
- pairing secret is transported through encrypted SSH stdin and is not returned to the Dashboard browser.

For a first connection, the Controller service account must already trust the host key through its OpenSSH `known_hosts` policy. A future credential/fingerprint management surface may make this easier without weakening host-key validation.

## Pairing order

The order is intentionally security-sensitive:

```text
validate request
  -> validate Controller + Region + Datacenter
  -> validate preconfiguration
  -> SSH preflight
  -> existing-Agent check
  -> issue one-time pairing token
  -> persist installation metadata/preconfiguration
  -> remote bootstrap
  -> enrollment
  -> bind Agent location
  -> apply preconfiguration
  -> heartbeat online
```

A failed SSH preflight creates no pairing token.

If the token has already been issued and the remote bootstrap subsequently fails, the token is expired immediately instead of remaining usable until its original TTL.

## Preconfiguration lifecycle

A port range cannot belong to an Agent that does not yet exist.

Therefore the Dashboard does **not** insert an early row into `agent_port_ranges`.

Before enrollment, settings are stored under:

```text
agent_installation_preconfiguration
    installation_id -> agent_pairing_tokens.id
```

After enrollment establishes `agent_id`:

1. the intended Datacenter is bound to `agent_locations`;
2. the optional administrative name is applied to `agents.name`;
3. the port range is applied through the existing `AgentPortRepository.set_ranges()` contract;
4. the preconfiguration records `applied_at` or `apply_error`.

This avoids orphan port allocations and keeps the Agent as the owner of its managed network range.

## Port range

The initial wizard supports:

```text
protocol: tcp | udp | both
start:    1..65535
end:      start..65535
```

The Dashboard defaults to:

```text
TCP + UDP
24000-24999
```

The values are defaults only and may be changed before installation.

`both` is materialized as independent TCP and UDP managed ranges after enrollment.

## Failure semantics

Agent enrollment is considered more important than optional administrative preconfiguration.

If enrollment succeeds but a preconfiguration step cannot be applied:

- the newly enrolled Agent is not deleted or rolled back;
- the failure is stored in `apply_error`;
- the Dashboard exposes the pending/error state;
- a later administrative retry can be implemented without re-enrolling the Agent.

For a newly enrolled Agent with no instances, port-range conflicts are normally impossible. The existing range repository still performs its standard safety checks.

## HTTP behavior

The implementation reuses the existing installation endpoints:

```text
POST /api/agents/installations
GET  /api/agents/installations/status?installation_id=...
```

No parallel pairing API is introduced.

For manual methods, `instruction` is returned as before.

For SSH remote installation:

```json
{
  "instruction": null,
  "remote_bootstrap": {
    "state": "completed",
    "host": "...",
    "ssh_user": "...",
    "ssh_port": 22,
    "platform": "linux",
    "architecture": "x86_64"
  }
}
```

The plaintext pairing token is never returned in the remote-install response.

## UI behavior

The **Adicionar Agent** panel becomes a small installation wizard containing:

- platform;
- installation method;
- SSH target fields when applicable;
- Controller;
- Region/Datacenter;
- administrative name;
- managed port protocol/start/end;
- installation progress.

When SSH is selected, Windows is disabled; when WinRM is selected, Linux is disabled. Windows remote bootstrap uses the prepared HTTPS certificate profile.

## Initial implementation trade-off

The SSH bootstrap itself is synchronous in the first version: the HTTP request remains open while the bounded SSH bootstrap executes (default timeout 900 seconds, accepted range 30–3600 seconds).

This keeps the first implementation aligned with the already-tested SSH deployment transport and avoids introducing a second execution model in the same change.

For large fleets, the recommended evolution is a durable Controller deployment-job queue with:

- persisted job state;
- bounded worker concurrency;
- cancellation/timeouts;
- retry policy;
- audit history;
- progress streaming/polling.

That evolution does not change the pairing or preconfiguration data model introduced here.

## Migration numbering

This feature uses migration `026_agent_installation_preconfiguration.sql`.

Migration 025 is intentionally left available for the already-open Agent game-data orchestration work. The migration engine loads versioned files in numeric order and can apply a previously missing version later.

## Non-goals

This first version does not add:

- Windows remote bootstrap is implemented by the WinRM HTTPS flow documented in `windows-winrm-remote-deploy.md`;
- SSH password storage;
- private-key upload through the Dashboard;
- host-key bypass;
- automatic Agent reinstall;
- multi-host/batch deployment;
- permanent SSH administration after enrollment.

## Architecture boundary

No feature logic is added to the large `dashboard/server.py` module.

The implementation extends the existing modular Agent installation API, adds a dedicated preconfiguration repository/migration, and updates the Agents UI.
