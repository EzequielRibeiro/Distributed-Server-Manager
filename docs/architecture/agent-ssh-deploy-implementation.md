# Agent SSH Deploy — Implementation Scope

## Status

Implemented on branch `feat/agent-ssh-deploy`, pending CI/merge.

## Command

```bash
cap agent deploy HOST --ssh-user USER
```

Example for the current LAN topology:

```bash
cap agent deploy 192.168.15.55 --ssh-user ezequiel
```

If `--controller-url` is omitted, the CLI determines the local source address the Controller would use to reach the Agent and uses dashboard port 8080 by default. It can be overridden with `DSM_CONTROLLER_URL`, `DSM_DASHBOARD_PORT`, or the explicit CLI option.

## Initial authentication scope

The first implementation is intentionally automation-safe:

- OpenSSH client is required on the Controller;
- SSH authentication uses existing keys, ssh-agent, or `--identity-file`;
- no `--password` argument exists;
- remote `sudo` must be usable non-interactively (`sudo -n`);
- host-key verification is not disabled by Capivara;
- pairing tokens are delivered through encrypted SSH stdin and are not included in the local SSH argv;
- no `shell=True` execution is used.

Interactive password-based bootstrap can be designed later without changing the logical `cap agent deploy` contract, but it must not introduce passwords in CLI arguments or logs.

## Operation order

1. Resolve active Controller identity.
2. Resolve the Controller URL reachable from the Agent.
3. Run read-only SSH preflight.
4. Refuse deployment when an existing Agent installation is detected.
5. Issue a short-lived one-time pairing token.
6. Start the official Agent bootstrap over SSH.
7. Wait for enrollment.
8. Wait for Agent status `active` and health `online`.
9. Return success without printing pairing/permanent credentials.

Pairing is deliberately issued only after SSH preflight succeeds.

## Modules

- `bin/cap`: command routing only.
- `database/agent_deploy_cli.py`: Controller/database orchestration and CLI presentation.
- `core/agent_ssh_deploy.py`: SSH transport, preflight, bootstrap and wait logic.
- `tests/agent_ssh_deploy_test.py`: deterministic tests with injected SSH runner.
- `.github/workflows/agent-ssh-deploy.yml`: dedicated CI/security gate.

No new functionality was added to `dashboard/server.py`.

## Explicit non-goals for v1

- remote Windows deployment;
- password arguments;
- automatic host-key bypass;
- automatic reinstall of an existing Agent;
- permanent SSH-based Agent administration;
- deployment to multiple hosts in one command.

After bootstrap, normal operations use the authenticated Controller-Agent protocol rather than SSH.
