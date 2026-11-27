# Controller TLS certificate lifecycle

DSM serves HTTPS directly. The lifecycle uses a root-owned systemd timer and a
provider-controlled certificate source. It verifies the full chain, validity
window, hostname or IP, key match and readability as the installed Dashboard
account. It then switches one symlink to an immutable pair under
`/etc/capivara/tls/versions`. New connections load the selected pair in the
running Dashboard. Existing connections retain their current TLS context.

The deployment commits after a loopback request with the public TLS identity,
trusted CA, exact candidate leaf and HTTP 200 with a healthy `/health` response.
An activation failure restores the prior pointer and checks its HTTPS health.
A durable pending record lets systemd recover an interrupted activation in
`ExecStopPost` or on the next timer invocation. The same rejected pair requires
operator review before retry. Renewal, verification and rollback do not call
`systemctl restart` or manipulate game units. The #928 updater still performs its
independent admission, compatibility and recovery checks. Rotation takes a
shared lock on its existing updater admission inode when provisioned.

## Source selection and enrollment

- **New ACME install**. Select HTTPS and ACME in the installer. Use
  `DSM_TLS_ACME_CHALLENGE=http-01` for Certbot standalone on public TCP/80, or
  `dns-01-hook` with `DSM_TLS_DNS_AUTH_HOOK` and `DSM_TLS_DNS_CLEANUP_HOOK`.
  The historical `letsencrypt` mode name accepts an alternate HTTPS ACME
  directory through `DSM_TLS_ACME_SERVER`. Certbot stores the server and
  challenge in its lineage. The CA must already be trusted on Controller and
  Agents. An interactive legacy DNS-01 lineage must be reconfigured for
  unattended renewal or switched to an external publisher before acceptance.
- **Existing Controller or external issuer**. Use an approved DSM candidate
  with the live TLS loader running first. When migrating the historical native
  paths `/etc/capivara/tls/server.crt` and `server.key`, leave the working pair
  in place for the initial rollback. If the Controller uses other files,
  arrange an authorized Controller configuration change to that native
  layout, preserving the previous pair and trust configuration. Once a
  managed generation is verified, the explicit paths
  `/etc/capivara/tls/active/server.crt` and `server.key` can be persisted at the
  next authorized Controller configuration change so older Dashboard code can
  load the active pair at startup.
- From the verified DSM installer tree, as root, source
  `installer/web_transport.sh` and run `install_controller_tls_lifecycle` during
  enrollment. This installs the root program and unit files, reloads systemd,
  and removes the legacy nontransactional Certbot deploy hook. Confirm no
  legacy hook is already executing. Preserve a copy of the current TLS setup
  in root-only storage before migration.
- Create `/etc/capivara/controller-tls.json` as root (mode `0600`). Set
  `hostname` to the public TLS identity, `address` to the locally reachable
  numeric bind address (defaults to `127.0.0.1`), `port` to the internal HTTPS
  port, and the service account to the actual User and Group reported by
  `systemctl show dsm-dashboard.service -p User -p Group`. For a private issuer
  set `ca_file` to the root-controlled trust bundle and configure the same
  trust on DSM and Agents. For Certbot replace the two source keys below
  with `"certbot_lineage": "controller.example.com"` using the actual lineage
  name. Keep the ACME account files and DNS credentials root-owned and
  root-readable only. DNS hooks must avoid logging credentials and use the
  narrowest DNS permissions available for the challenge zone.

```json
{
  "hostname": "controller.example.com",
  "address": "127.0.0.1",
  "port": 8443,
  "service_user": "dsm",
  "service_group": "dsm",
  "source_cert": "/etc/capivara/issuer/fullchain.pem",
  "source_key": "/etc/capivara/issuer/privkey.pem"
}
```

An external scheduler issues/renews independently and publishes a PEM fullchain
and unencrypted PEM key under a root-controlled directory. Publish the source
pair together through a generation directory and an atomic symlink switch.
Use mode `0600` for the source key. The installed pair uses root ownership,
Dashboard group, directories `0750` and files `0640`. Start the rotation once
with `systemctl start dsm-controller-tls.service`. After it succeeds, run
`systemctl enable --now dsm-controller-tls.timer`. The timer runs after boot
and then roughly every six hours. It deals only with the configured lineage.
Keep other Certbot lineages and their scheduling intact.

## Monitoring and recovery

Use `journalctl -u dsm-controller-tls.service` and the unit's failed state.
Route journal priority warning and above for `capivara-controller-tls` to the
site's existing alert destination. Expiry events are sent on entry to the 30,
15, 7 and 1 day windows and on expiry. A host that misses timer runs reports its
current urgency when it comes back. Renewal, invalid artifacts, access,
rollback and HTTPS faults are surfaced as actionable journal events without PEM
or provider output. Retain diagnostics for the installed Certbot locally under
its protected log directory.

1. On failure, check systemd, the activity journal, public hostname and local
   address/port, then confirm the current leaf with verified HTTPS. Check
   source/trust ownership and modes, CA chain, time and the configured
   provider's completion. Fix the renewal source before triggering the service
   again.
2. If a valid pair was rejected because of an unrelated readiness failure,
   resolve the underlying Dashboard fault, then run
   `sudo /usr/bin/python3 -I -S -B /etc/capivara/controller-tls-lifecycle.py --retry`.
   The same validation, locks and rollback apply. The helper's `--verify-active`
   performs a read/verify check of the current pair and its served HTTPS.
3. If the previous certificate is unusable, deploy a corrected trusted pair.
   If the Dashboard cannot start at all, keep the timer stopped, preserve the
   configuration and key material, and use the authorized recovery window to
   restore a trusted pair. Use the managed installer bootstrap only for a new
   empty TLS store. Start the Controller once after repair, verify HTTPS and
   re-enable the timer. Use the DSM updater's own recovery procedures for
   product rollback and never repoint only one member of a certificate pair.

A deployment probe verifies the local Controller. During the bounded probe,
new connections can see the candidate. After a host crash, the candidate can
remain selected until systemd runs recovery. Any proxy, published port,
external DNS routing, real Agent trust and continuity must be checked separately
in the integrated procedure below. A failing underlying `/health` causes
certificate deployment to roll back even when the candidate is cryptographically
valid. If no active certificate is valid, restoring an old
pointer cannot restore verified service. Local self-signed mode still uses
explicit trust. Rotating its trust anchor requires coordinated Agent trust
migration before enrollment.

## Single operational acceptance procedure

Use one evidence record for all three checks. Use the reviewed commit/package
and isolated systems with an approved Horizon and external VPS topology.
Require explicit separate authorization before touching production hosts.

1. **Isolated scheduled success**. Enroll one of the supported sources on the
   disposable Controller. Record the exact build SHA, timer status, source
   mode, active pointer, file owner/mode, old leaf fingerprint, Controller
   PID and both game process identities. Have the chosen publisher complete a
   renewal and let the timer run. Capture `activation_verified`, the new leaf
   and healthy `/health` with ordinary trusted HTTPS, plus the original
   Controller and game PIDs. Record the CI Controller TLS Transport run
   containing Linux and Windows installer syntax checks, transport, lifecycle
   and updater readiness tests. CI uses an isolated CA and a fake Certbot
   adapter, with real file permissions and HTTPS in the runner.
2. **Isolated failure injection**. With the previous leaf still valid, publish a
   mismatched pair, then a pair with a bad source key mode or simulate a
   renewal failure. Confirm failed unit/journal, unchanged active leaf and
   PIDs, and verified health. In the same run force a readiness failure after
   candidate activation and show pointer rollback, verified prior HTTPS, and
   no repeated activation of the rejected pair. Restore a healthy fixture at
   the end. Record failure codes and fingerprints without key material.
3. **Integrated Horizon and external VPS**. With the approved test endpoints,
   record baseline UTC time, identities (unit, PID and start time) for active
   games on both hosts, public served leaf from the VPS, Agent heartbeat and
   representative console stream cursor. Perform one normal timer-driven
   rotation at the Controller. From the VPS, verify HTTPS using normal CA and
   hostname validation, the new leaf, a fresh authenticated Agent heartbeat,
   and console frames after the baseline cursor. Confirm the exact before and
   after process identities on both hosts and the Controller restart count
   during the same window. Attach redacted evidence to #1161 before closing it
   or unblocking release.
