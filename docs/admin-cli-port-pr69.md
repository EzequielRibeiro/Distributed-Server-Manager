# Administrative CLI port from PR #69

This branch ports the still-relevant administrative workflow from the historical PR #69 onto the current Capivara DSM 2.0 mainline.

Canonical commands are exposed through `cap`:

- `cap customer create ...`
- `cap contract create ...`
- `cap contract delete ...`
- `cap instance create ...`
- `cap instance delete ...`

The port keeps placement eligibility checks when an Agent is explicitly selected, queues distributed provisioning through the existing Agent pipeline, and makes deletion confirmation-driven: the Controller only purges instance persistence and port reservations after the owning Agent reports successful runtime removal.

Migration number `041` is used because current `main` already owns migrations `037` through `040`. SQLite, PostgreSQL and MySQL/MariaDB variants are included.

The legacy PR branch is not merged directly because it diverged substantially from the current 2.0 baseline.
