# Administrative CLI port status

Status: integrated into current `main`.

The administrative workflow originally developed in historical PR #69 was ported onto the current Capivara 2.x baseline and merged through PR #82.

Available through the canonical public CLI `cap`:

- customer creation with scoped login;
- service contract create/delete;
- explicit Agent selection without bypassing placement eligibility;
- distributed instance creation through the existing provisioning queue;
- Agent-side runtime removal action;
- confirmation-driven instance purge and port release;
- contract purge only after linked instances are gone;
- Controller/Hybrid role enforcement;
- migration 041 parity for SQLite, PostgreSQL and MySQL/MariaDB;
- focused CI coverage.

The current operational reference for Customer, Contract and Instance administration is:

```text
docs/administracao-customer-contract-instance.md
```

It documents the distinction between `cap customer create` and `cap user add ... customer <scope>`, customer login routes, Customer membership, instance permissions, contract creation, instance creation and deletion, and troubleshooting for customer access.

The DayZ remote-Agent worked example remains available at:

```text
docs/tutorial-instalacao-dayz-agent-remoto.md
```

The historical PR #69 is closed as superseded. It must not be merged directly.

`dsm` is not an administrative CLI alternative. It remains only as a temporary compatibility wrapper that forwards old invocations to `cap`. New documentation and automation must use `cap`.
