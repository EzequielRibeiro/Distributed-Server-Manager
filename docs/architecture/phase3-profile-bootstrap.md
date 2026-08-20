# Phase 3 — installation profile bootstrap

Status: implementation contract

This phase connects the installation profile selected by `install.sh` to the persistent Registry immediately after database initialization.

The installer order is normative:

```text
initialize_database
        ↓
initialize_infrastructure_identity
        ↓
install_cli
        ↓
install_systemd_units
```

The bootstrap is deterministic and idempotent. Reinstallation must reconcile the same local identity and must not force an existing disabled/offline object back to `active`.

## Controller profile

A fresh `controller` installation creates:

```text
Node(role=controller, status=active)
└── Controller(status=active)
```

It does not create an Agent.

Therefore a fresh Controller has no placement candidate and is not able to host a game instance until at least one usable Agent is enrolled.

The deterministic IDs are derived from the local hostname:

```text
node_id       = <hostname>
controller_id = controller-<normalized-hostname>
```

## Standalone Agent profile

A remote standalone `agent` must not invent a Controller.

The current relational model requires every persisted row in `agents` to reference a real Controller through `agents.controller_id`. For that reason, the pre-pairing local identity is represented by the local Node:

```text
Node(role=agent, status=pending)
```

The installer also writes the deterministic local Agent identity to `config/agent.conf`:

```text
DSM_NODE_ID=<hostname>
AGENT_ID=agent-<normalized-hostname>
AGENT_STATUS=pending
```

No fake Controller and no orphan `agents` row are created.

When secure enrollment is completed, the Controller-side registration flow creates the authoritative Controller-owned `agents` record using the Agent identity.

This preserves the schema invariant instead of weakening `agents.controller_id` merely to support an unpaired machine.

## Hybrid profile

A fresh `hybrid` installation is trusted locally and can bootstrap a complete infrastructure chain automatically:

```text
Node(role=hybrid, status=active)
├── Controller(status=active)
└── Agent(status=active)
    └── Agent Location(active)
        └── Datacenter(active)
            └── Region(active)
```

Controller and Agent share the same hybrid Node. This is supported by the existing ownership triggers, which accept a Node whose role is `hybrid` for both Controller and Agent records.

The default local topology uses deterministic per-host IDs:

```text
controller-<host>
agent-<host>
region-local-<host>
datacenter-local-<host>
```

A fresh Hybrid installation therefore satisfies the infrastructure side of the placement predicate immediately:

```text
Controller active
AND Agent active
AND Agent Location active
AND Datacenter active
AND Region active
= placement_ready
```

Customer/contract creation remains a separate administrative concern, but no manual database manipulation is required to make the local Hybrid Agent available for the first server placement.

## Registry ownership

Profile bootstrap is implemented through `RegistryRepository.bootstrap_installation_profile()` and exposed by:

```text
database/registry.py bootstrap-profile
```

`install.sh` invokes this command after database migrations have completed.

The installer passes the selected database backend through the same `DSM_DATABASE_*` environment contract used by runtime services, so SQLite, PostgreSQL and MySQL/MariaDB use the common backend abstraction.

## Reinstallation behavior

Bootstrap is safe to run again for the same profile and hostname.

Matching existing identities are reused. Existing lifecycle status is preserved rather than overwritten. In particular:

```text
Hybrid Agent offline + reinstall -> remains offline
Controller disabled + reinstall   -> remains disabled
```

Identity collisions fail closed. For example, a standalone Agent installation cannot silently reuse a Node that is already persisted as a Controller-only Node.

## Phase boundary

This phase provides local/bootstrap identity creation. It does not implement the secure remote pairing transport itself.

For a standalone Agent, the transition from local pending identity to an authoritative Controller-owned Agent continues to depend on the secure enrollment/pairing work.
