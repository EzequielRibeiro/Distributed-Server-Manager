# Instance relocation across Agents — gated rollout

Status: **draft / disabled by default**. Do not deploy or enable this workflow
against live customer data before successful cross-host recovery tests. This
change does **not** automatically move an instance during a resource-profile
upgrade. The initial scope is an explicitly confirmed administrative relocation.

## Operator flow

1. Verify **two distinct enrolled and healthy physical hosts**, runtime and
   OS/architecture compatibility, profile capacity and available destination
   TCP/UDP blocks. The Controller and customer contract remain unchanged.
2. Ensure the customer has been notified of downtime. Preserve a tested,
   recoverable external PostgreSQL snapshot and private instance data snapshot.
3. In an isolated two-Agent environment, enable
   `CAPIVARA_ENABLE_AGENT_RELOCATION=1` on the Controller **only after**
   verifying Linux root-helper and/or Windows service permissions and the
   tested end-to-end rollback scenario.
4. Controller instance administration → **Mover instância para outro Agent**:
   select the destination, run preflight, and type the exact instance ID
   to confirm the offline migration.
5. Monitor the relocation status through the administrative endpoint
   `GET /api/admin/instance/agent-relocation?instance_id=…`.
   Preserve the source's private data and its fenced service until the
   destination has been checked and decommissioning is explicitly approved.

## State and consistency model

The Controller queues an authenticated relocation-phase **stop** command
(compatible with the existing database action allowlist), handled by newer Agents
as durable **fencing**, which disables
Linux systemd autostart through its validated root materializer helper, or
changes Windows SCM start type to disabled. It then stops the original runtime
and confirms the result. Local Agent start/restart paths reject a durable fence
marker. Only a completed fence permits backup.

The source produces a stopped, full, gzip backup; its checksum, length,
instance ID and runtime manifest are validated after artifact export. Destination
ports are held transactionally, including allocations made by other concurrent
migration requests. Ownership, reserved ports, instance manifest path,
network metadata and canonical backup-policy owner change in one transaction,
while original ports remain held for recovery.

The destination is provisioned **stopped**. The verified archive is imported
through the artifact plane, restored, and only then started (if the source was
originally online). Successful completion requires the target's own health
report. The original startup remains disabled and private files are retained.

Before cutover, a confirmed source fence can be undone and the source restarted.
After cutover, the source cannot be unfenced until the target Agent has **explicitly
confirmed shutdown**, then the original metadata, ports and startup policy are
restored. Unknown results or partially provisioned targets enter
`manual_recovery`; never assume two Agents cannot concurrently start a server.

Events and operation IDs remain in the Controller database. All mutating
customer operations, maintenance backups, retries and instance deletion are
blocked during unresolved relocation. The Controller uses a durable per-operation
lease so overlapping heartbeats do not issue duplicate phase transitions.

## Important limits / release gates

- The HTTP mutation endpoint is **disabled unless**
  `CAPIVARA_ENABLE_AGENT_RELOCATION=1`. Preview and history remain available.
- Validate the new additive Baseline v22 schema on
  **PostgreSQL**, MySQL/MariaDB and SQLite; don't assume SQLite tests cover all.
- Verify Linux privileged systemd helper/polkit and Windows SCM startup-mode
  restoration with **two actual hosts**; simulated Windows tests are not native
  Windows acceptance tests. Include source reboot during transfer, destination
  restore failure, lost heartbeat/lease recovery, conflicting port allocations,
  interrupted transfer, and rollback **of world data** after the new process
  has touched the restored data.
- Prove the backup covers installed workshop content, maps, Java worlds/config,
  and game-specific external files as appropriate. Missing or non-portable
  assets must fail preflight until a portable bundle is available.
- Document and implement operator-verified `manual_recovery` before enabling
  the mutation endpoint for customers. Do not delete the source, its port hold
  or the original backup automatically after success.
- Do not enable migration during a scheduled backup, maintenance operation,
  profile transition or version update. Automatic destination selection on
  profile upgrade is a **separate follow-up**, after manual flow certification.
- Apply to `/opt/dsm` only after a verified PostgreSQL and instance-data backup.
  No automatic merge, release or live instance migration from this draft.
