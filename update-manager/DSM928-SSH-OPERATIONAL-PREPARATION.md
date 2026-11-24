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
This standalone-only transport does not yet establish the complete global
inventory partition, actual daemon coverage, external-job fencing, official
artifact trust, or production updater integration. Keep no-drain blocked.
