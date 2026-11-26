# Issue #928 — operational SSH preparation

This is an **explicit operator procedure**, not an installer or an update
authorization. Do not run PREPARE, apply or rollback on production using this
document. The read-only probe does not verify that all mutators are fenced.

## Prerequisites

* Independently review the exact candidate and verify its signed release bytes.
  Provision the official publisher trust anchor separately. Do not execute
  unverified downloaded Python as root.
* On the Controller and each standalone Agent, stage the nine modules listed
  in `MODULES` in `game_uptime_ssh_transport.py` from the same verified
  candidate in `/usr/local/libexec/capivara-dsm-928-agent/`. All ancestor
  directories and files must be root-owned, without group/other write
  permission, regular files with one link. No symlink, no automatic copy
  from the mutable installed Agent directory. Review existing snapshots
  instead of overwriting them during a pending transaction.
* Each Agent must have a root-owned 0600
  `/etc/capivara-dsm/agent-session-id` containing exactly its independently
  verified Agent ID followed by one newline.
* Controller: root-owned 0600 `/etc/capivara-dsm/agent-session-ssh-key` with a
  dedicated key, and root-owned 0600
  `/etc/capivara-dsm/agent-session-endpoints.json` mapping every expected
  standalone Agent ID to an object containing `host`, integer `port` and
  `host_key` (the exact independently verified ssh-ed25519 public host key,
  algorithm and base64 blob, no comment). Never learn pins by blindly
  trusting the first network connection. The inventory must not silently
  omit an offline Agent.
* If the existing SSH security policy permits, authorize **only** this
  dedicated Controller public key using a restricted forced command in the
  remote root authorized_keys file:
  ```text
  restrict,command="/usr/bin/python3 -I -S /usr/local/libexec/capivara-dsm-928-agent/game_uptime_ssh_transport.py --serve" ssh-ed25519 <DEDICATED_PUBLIC_KEY_BLOB>
  ```
  Do not enable root SSH globally, disable restrictions, enable password
  authentication or change firewall rules merely to make this probe succeed.
  A host incompatible with this policy remains blocked. The Controller's
  private key must never leave the Controller.

## Probe only

Run as root on the Controller using the reviewed snapshot and pass the complete
independently determined standalone Agent inventory (placeholder IDs below):

```sh
/usr/bin/python3 -I -S /usr/local/libexec/capivara-dsm-928-agent/game_uptime_ssh_transport.py --probe AGENT_ID_1 AGENT_ID_2
```

Exit 0 requires every pinned host to pass SSH authentication, its local ID
and a unique protocol challenge. Exit 2 means blocked. The probe never creates
a maintenance hold or pending journal, stops games, or authorizes an update.

The Hybrid Agent on the Controller must be accounted for by the local scope,
not probed as a standalone Agent unless independently deployed as such.
The installed-scope coordinator now also requires the Controller's
root-owned 0600 agent-session-id with its independently verified Hybrid ID.
Its root-only retained-scope primitive accepts the full independently
reviewed inventory and exact shared time window, validates the SSH endpoint
partition and retains the local and remote fences together. It is not an
operator entrypoint: do not invoke it to apply a release. Actual daemon
coverage, external-job fencing, production apply and installed terminal
release remain unverified. Keep no-drain blocked.

## Remaining operational admission boundary

The first supported no-drain operation is scoped to the Controller,
Dashboard, and Workers on one host. Standalone and local Hybrid Agents must
keep running on the same version. Agent code, game adapters, supervisors,
database changes, and incompatible dependencies require conventional
maintenance. The controller-side command store and its schema must remain
compatible with both versions throughout activation and rollback.

Controller unavailability during restart is expected. Commands retain their
IDs across heartbeat retries, and the Controller must commit a terminal
result and its console output together so a lost reply cannot duplicate the
output. This covers a Controller restart with the Agent still running.
Restarting an Agent that may have an unresolved command is outside this
scope.

The installed executor and its recovery now use the host's locks and journal.
Controller registry rows are checked locally. External Agents do not take
part in preparation or terminal release. The prior distributed journal format
requires administrative review and cannot be recovered as a host transaction.
Manual administrative operations that change DSM units, game state, or the
reviewed package are prohibited during the transaction.

The systemd adapter checks the hold across start, stop, restart, and any
post-stop reset-failed call. A split restart retains the same guard across
both actions. Read-only status and doctor calls remain available. The
Controller topology service takes the existing privileged helper lock before
reconciling units. A normal bootstrap must install the guarded service before
it can count as coverage.

Admission remains blocked until installed coverage is verified for Hybrid
callers and direct helper launches. These include unit materialization and
daemon-reload, native/DayZ operations, backup/restore, firewall, and customer
file-access helpers. An idle job queue and a settled topology service alone
do not verify these paths.

The coverage verifier compares pinned mutator source with the independently
installed updater snapshot, checks both Hybrid worker identities and helper
selectors, and verifies effective systemd fragments against the rendered
templates. Unknown helper units, drop-ins, and stale workers block admission.
Disposable CI can exercise the verifier without enrolling a host. Installing
the reviewed snapshot and proving coverage against the real installation
belong to the deployment phase.

A green CI is not permission to install or execute the no-drain updater.
The read-only review now separates preparation blockers from retained ACKs.
The installed owner checks preparation eligibility before creating a hold,
then requires the exact transaction-bound, authenticated retained scope
before product mutations or terminal release. Missing host evidence for
mutator coverage still blocks preparation. Compatibility and game inventory
must also be independently verified. Do not flip those flags
or manufacture receipts to bypass the gate. The existing signature was for
an earlier candidate, not the current HEAD. The first fence-aware release
changes systemd/Agent/updater code and may require separately approved
maintenance; never fall back to a draining update automatically.

The read-only preflight consumes a canonical, independently reviewed
`operational-inputs.json` beside the signed release. Its schema version is
1. It names the verified archive SHA-256, installed version, Controller and
Agent compatibility contracts, exact expected active unit names and the
Minecraft supervisor SHA-256. The supervisor version directory is the
root-owned `supervisor-versions` sibling of `reviewed-release`. The
executor re-reads these inputs under the retained scope and re-checks the
game witnesses before preparing the file journal.

The restart candidate in the file plan does not establish service ownership
or claim a rollback result. Ownership comes from the retained service
inventory and fixed restart operation. Before mutating files, the executor
verifies the journal's original bytes. It checks the resulting bytes and
restart receipts at the terminal boundary.

The original Controller/Worker/alert identity and registry/queue inventory
are now bound to the same transaction across reconnects. A missing or changed
witness blocks recovery. This is additional evidence, not proof of live
coverage, expiry/reboot recovery, or Python control-plane restart compatibility.

The installed transaction owner also has an internal `--recover TRANSACTION_ID`
entrypoint. It validates the original canonical journal and signed payload,
reacquires the original unexpired scope, verifies terminal bytes or rolls
back a prepared mixed file state, and never renews a lease. It remains
blocked by missing positive retained operational guarantees. Do not run it
against production during this implementation phase; expired, rebooted,
missing or partially released scopes still require explicit manual review.
