# Capivara DSM 2.0.98

Corrective DayZ runtime release for Steam IPC isolation and stable launcher metadata.

## Fixes

- Isolates DayZ `/dev/shm` per systemd instance with a private tmpfs so stale Steam IPC state cannot leak across restarts or other processes sharing the runtime UID.
- Prevents the DayZ query extension from advertising the spurious `sakhal` entry with Workshop ID `0` after stale Steam IPC reuse.
- Keeps the isolation profile-driven through a generic `private_shared_memory` RuntimeSpec capability instead of embedding DayZ-specific logic in the generic systemd materializer.
- Bumps the DayZ runtime profile to version 11 so existing persisted RuntimeSpecs migrate and receive shared-memory isolation automatically.
- Retains the v2.0.97 DayZ relative Workshop aliases and graceful SIGINT shutdown behavior.

## Validation

- Live A/B testing on the Horizon hybrid host isolated the fault to stale `/dev/shm/u995-*` Steam IPC files for the shared `capivara-instance` UID.
- After a clean stop, stale IPC cleanup and restart, A2S returned CF, CodeLock and VPP metadata without `sakhal`.
- A live systemd drop-in using `TemporaryFileSystem=/dev/shm:rw,nosuid,nodev,mode=1777` produced distinct host/unit shared-memory inodes and preserved correct A2S output.
- PR #726 passed all 25 triggered GitHub workflow gates on its final head, including CI, Agent Instance Runtime, DayZ Native Restart, M10 Final E2E Release Validation and External Controller Agent E2E.
