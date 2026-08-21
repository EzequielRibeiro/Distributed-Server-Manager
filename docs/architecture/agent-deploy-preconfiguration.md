# Agent deploy preconfiguration

## Goal

`cap agent deploy` and the Controller Dashboard must use the same pre-enrollment configuration model for a new Agent.

The CLI does not write `agent_port_ranges` before the Agent exists. It stores the requested settings against the pairing/install record through `AgentInstallationPreconfigurationRepository`. After enrollment creates the definitive `agent_id`, the existing enrollment binding applies the administrative name and managed port range.

## CLI

Example:

```bash
cap agent deploy 192.168.15.55 \
  --ssh-user usuario \
  --name "Agent Limeira 01" \
  --region-id br-se \
  --datacenter-id limeira \
  --port-range 24000-24999 \
  --port-protocol both
```

New options:

- `--name NAME`: administrative Agent name applied after enrollment.
- `--port-range START-END`: managed range to apply after enrollment.
- `--port-protocol tcp|udp|both`: protocol associated with the range. When omitted with `--port-range`, the default is `both`.

`--port-protocol` without `--port-range` is invalid.

Valid ports must satisfy:

```text
1 <= START <= END <= 65535
```

Examples such as `24999-24000`, `0-1000`, `24000-70000` or non-numeric ranges are rejected before pairing-token issuance.

## Lifecycle

```text
cap agent deploy
        |
        v
validate CLI/topology/range
        |
        v
SSH preflight + existing-Agent check
        |
        v
issue pairing token
        |
        +--> annotate Region/Datacenter
        |
        +--> persist Agent preconfiguration
        |
        v
bootstrap Agent over SSH
        |
        v
enrollment creates agent_id
        |
        +--> bind Datacenter
        +--> apply administrative name
        +--> apply TCP/UDP managed range
        |
        v
Agent online / placement eligible when runtime requirements are satisfied
```

## Port ownership

A configured range is the pool that the Controller is authorized to administer for that Agent. It does not reserve every port and does not imply firewall changes.

TCP and UDP remain independent resources. For example, applying only UDP `30000-30999` does not delete an existing TCP range.

The existing `cap agent ports ...` commands remain the administrative path for changes after installation.

## Dashboard parity

The CLI intentionally uses the same `normalize_preconfiguration()` and `AgentInstallationPreconfigurationRepository` introduced for the Controller Dashboard remote-install flow. This avoids separate validation or persistence rules for Dashboard and CLI.

Equivalent inputs from either interface must produce the same persisted preconfiguration:

```text
agent_name
port_protocol
port_start
port_end
```

## Security

The change does not alter the SSH trust model:

- no SSH password argument is introduced;
- no `StrictHostKeyChecking=no` behavior is added;
- the pairing secret continues to travel through the existing protected SSH bootstrap path and is not placed in the SSH argv;
- the range and name are administrative metadata, not secrets.

## Scope

This feature changes source behavior only. Installation on a real Agent, pairing-token issuance on an active Controller, database migration on `/opt/dsm`, or remote-host modification remain deployment operations and are outside source implementation/testing.
