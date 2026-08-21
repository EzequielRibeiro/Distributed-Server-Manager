# Agent lifecycle and upgrade hardening

## Scope

The Linux Agent owns local update execution. The Controller may request a desired
version, but it does not stream binaries and it never writes into the Agent
installation directory.

## Distribution source

Automatic `stable` and `beta` updates use the official GitHub Releases of the
configured Capivara repository. For a requested version `X.Y.Z`, the Agent
expects these immutable release assets:

- `capivara-agent-linux-X.Y.Z.tar.gz`
- `capivara-agent-linux-X.Y.Z.tar.gz.sha256`
- `capivara-agent-linux-X.Y.Z.manifest.json`

The archive checksum is verified before extraction. The external manifest must
match the manifest packaged inside the archive, and all required package files
are verified against their manifest SHA-256 values.

The source is intentionally represented by the update metadata and repository
configuration instead of being coupled to Controller file serving. This leaves
room for a future signed update-manifest service/CDN without changing the
Controller/Agent ownership boundary.

`local/manual` remains explicit administrator territory and is never downloaded
automatically by the privileged updater.

## Update lifecycle

1. Controller heartbeat response may carry a desired version.
2. The unprivileged Agent stages `update-request.json` under its state directory.
3. `capivara-agent-update.path` activates the root-only updater.
4. The updater downloads release archive, checksum and external manifest.
5. Package and Python syntax are validated before installation files are touched.
6. Existing managed files are snapshotted for rollback.
7. New files are atomically replaced.
8. `/usr/local/bin/cap` is reconciled only when absent or already owned by this
   Agent installation; foreign files are never overwritten.
9. Installed hashes and `VERSION` are validated.
10. The Agent service is restarted and must become active.
11. Success/failure is written to the current result and local update history.
12. Any failure after replacement starts restores the previous managed files and
    previous CLI symlink before attempting to restart the old Agent.

## Local CLI

The following commands are observational and never stage or apply an update:

```text
cap agent update status
cap agent update history [--limit N]
cap agent update check [--channel stable|beta]
```

`check` queries GitHub Releases and compares release metadata with the installed
Agent version. It does not write `update-request.json`.

## Privilege policy

Agent identity/configuration remains private (`0600`) under the Agent service
account. The project does not weaken those permissions merely to make local CLI
usage convenient. Administrative local inspection may therefore require
`sudo cap agent ...` until a dedicated privileged local API/socket is introduced.

Only the dedicated systemd updater executes file replacement under
`/opt/capivara-agent` and CLI reconciliation under `/usr/local/bin`. Read-only CLI
commands do not cross that boundary.

## Compatibility

A pre-Agent-Local-Core installation may not have `/usr/local/bin/cap`. A normal
upgrade now creates the missing symlink after validating that no foreign command
already occupies that path. Existing Capivara-owned links are refreshed; foreign
paths fail closed.
