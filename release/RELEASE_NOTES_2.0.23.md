# Capivara DSM 2.0.23

Hotfix release for the Controller update path.

## Fixed

- Prevents rollback from restoring raw systemd unit templates containing `{{DSM_USER}}` / `{{DSM_GROUP}}` placeholders into `/etc/systemd/system`.
- Renders the restored runtime account before `systemctl daemon-reload` during rollback.
- Adds a packaging-time guard that fails the release build if the rollback hotfix is not present or leaves the packaged updater syntactically invalid.

## Operational note

This release supersedes the broken Controller package from v2.0.22. Agent artifacts remain built from the same release pipeline, while the Controller release package contains the rollback safety correction.
