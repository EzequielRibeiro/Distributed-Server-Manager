# Administrative CLI port from PR #69

The administrative workflow from historical PR #69 was ported onto the current Capivara DSM 2.0 mainline and is exposed through the canonical public CLI, `cap`.

Supported administrative commands include:

- `cap customer create ...`
- `cap contract create ...`
- `cap contract delete ...`
- `cap instance create ...`
- `cap instance delete ...`

The port keeps placement eligibility checks when an Agent is explicitly selected, queues distributed provisioning through the existing Agent pipeline, and makes deletion confirmation-driven: the Controller only purges instance persistence and port reservations after the owning Agent reports successful runtime removal.

Migration number `041` is used because the 2.0 line already owns migrations `037` through `040`. SQLite, PostgreSQL and MySQL/MariaDB variants are included.

The historical PR branch was not merged directly because it diverged substantially from the current 2.0 baseline. `dsm` must not be used as the documented administrative entry point; it remains only a temporary compatibility command for older installations and scripts.
