# Capivara DSM 2.0 Operational Runbook

## Install
Use the supported installer for the target Controller/Agent role. Validate health, database status and Agent enrollment before provisioning instances.

## Upgrade
1. Create and validate a control-plane backup/recovery point.
2. Confirm Agents are healthy and no destructive operation is in progress.
3. Run the supported update path.
4. Apply versioned database migrations only through the Capivara database layer.
5. Validate Controller health, Agent heartbeat, placement, API, events and a representative instance lifecycle.
6. Keep the previous package/recovery point until the post-upgrade gate is green.

## Rollback boundary
Do not silently reverse a database migration after new-version writes have occurred. If rollback is required past that boundary, restore the validated pre-upgrade recovery point and package set as one operation.

## Backup and restore
Use C5 Universal Smart Backup for instance data and E2 recovery points/control-plane backup for Controller state. Validate checksum and recovery-point state before restore.

## Federation
A datacenter remains locally authoritative for its Agents. During WAN partition, avoid topology reassignment guesses. Restore federation connectivity, then reconcile inventories and event cursors.

## HA failover
Promotion requires quorum, an eligible standby, successful fencing of the previous primary and the newest fencing epoch. If fencing cannot be proven, fail closed and retain local Agent runtime autonomy.

## Failback
Verify data convergence and stale-primary fencing before controlled failback. Failback is an administrative operation, not a reason to restart healthy game instances.

## Disaster recovery
Restore the latest validated recovery point within the declared RPO/RTO, validate database schema and control-plane identity, then reconnect federation and Agents. Run Infrastructure Doctor after recovery.

## Agent replacement
Enroll the replacement Agent with a new identity. Do not reuse a lost Agent credential blindly. Reconcile ownership and placement explicitly before moving workloads.

## Incident validation
After install, upgrade, failover, failback or restore, verify: database health, Controller identity, Agent heartbeat, placement eligibility, port reservations, events, observability, backup status, API status and instance desired/observed convergence.
