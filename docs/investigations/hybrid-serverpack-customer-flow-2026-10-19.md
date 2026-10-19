# Hybrid Agent Server Pack customer migration: investigation and acceptance criteria

Status: investigation; no implementation or production deployment in this branch.

## Reproduction (2026-10-19)
- Instance: `cli-000001-minecraft-005`, Agent: `agent-horizon-server`, runtime: NeoForge.
- Customer uploaded ATM11 `ServerFiles-0.12.0-beta.zip`; preview was validated, requiring NeoForge `26.1.2.109` from `26.1.2.94`.
- Production feature policy is allow-listed for this one instance/Agent on the test host.
- Agent provisioning `instance-provision-543b4156d73e43ce8eb3cb59497082ff` failed at `minecraft_serverpack_migration` with `PR855 homologation currently requires the instance to be stopped`.
- `dashboard/minecraft_serverpack_migration_service.py` enqueues `desired_state=stopped`, but `agents/linux/runtime/minecraft_serverpack_migration_provisioning.py` also requires observed instance state to be inactive before entering the migration.
- Customer sees pending content awaiting Agent completion and Controller atomic publication.
- The host had approximately 5.5 GiB free (96% used) at diagnosis; capacity may independently block migration.

## Required behavior
1. Customer explicitly confirms the attested preview; no migration starts merely because upload succeeds.
2. Controller creates a single idempotent migration operation, preserving immutable archive/plan evidence and exact instance/Agent authorization.
3. Agent coordinates an orderly instance stop as part of the customer-confirmed operation, verifies stopped state, validates a restorable backup and free space, and only then stages a candidate runtime.
4. Validate required NeoForge build, modpack and world preservation, publish content metadata atomically only after successful Agent completion, and provide a safe rollback/compensation path on failures.
5. UI must surface failed provisioning (with actionable reason) rather than leaving content indefinitely pending.
6. No cross-instance effect, no global migration feature enablement, no restart or modification of production Minecraft 005 during development/homologation.

## Tests to add
- Running instance customer-confirmed update: controlled stop and safe migration.
- Stop failure, insufficient capacity, missing/invalid backup, mismatched loader and changed preview fingerprint: fail closed without publishing.
- Retry after failed provisioning: no duplicate or partial publication.
- Controller/Agent mismatch or missing allow-list: denied.
- Successful Agent completion then atomic Controller publication; crash/retry boundaries.
- Customer status transition pending -> failed/completed with accurate error.

This note records the observed failure and work scope. It is not a code fix.
