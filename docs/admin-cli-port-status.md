# PR #69 port status

Port target: current `main` (Capivara DSM 2.0 line).

Included in this port:

- customer creation with scoped login;
- service contract create/delete;
- explicit Agent selection without bypassing placement eligibility;
- distributed instance creation through the existing provisioning queue;
- Agent-side runtime removal action;
- confirmation-driven instance purge and port release;
- contract purge only after linked instances are gone;
- canonical `cap` routes with Controller/Hybrid role enforcement;
- migration 041 parity for SQLite, PostgreSQL and MySQL/MariaDB;
- focused CI smoke coverage.

The historical PR #69 remains open until this replacement port is validated and integrated.
