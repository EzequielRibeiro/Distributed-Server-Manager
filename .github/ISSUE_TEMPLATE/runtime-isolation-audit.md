---
name: Runtime isolation audit
about: Audit a game runtime for shared mutable state between instances
---

## Runtime

- Game:
- Environment ID:
- Engine/profile:

## Shared content

List binaries/assets that may remain shared and SteamCMD/provider-managed.

## Instance-owned state

List configuration, saves/worlds/databases, profiles, logs and generated data that must be private.

## Isolation mechanism

- [ ] Private HOME/XDG paths are sufficient
- [ ] Explicit private argv/config paths
- [ ] `seed_files`
- [ ] `seed_directories`
- [ ] `bind_paths`
- [ ] Dedicated runtime profile required

## Forbidden shared writes

List any paths under the shared installation that the running server may modify.

## Two-instance verification

- [ ] A and B use the same shared game base
- [ ] A and B have distinct private state roots
- [ ] Config change in A does not change B
- [ ] Save/world/data change in A does not change B
- [ ] Concurrent start does not create shared-write collisions
- [ ] Game update preserves private A/B state
- [ ] Removing A leaves B intact

## Result

- [ ] PASS — isolated
- [ ] FAIL — correction required
