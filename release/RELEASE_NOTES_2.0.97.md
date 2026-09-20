# Capivara DSM 2.0.97

Corrective DayZ runtime release for graceful shutdown and Workshop mod activation metadata.

## Fixes

- DayZ managed updates now use graceful SIGINT shutdown semantics instead of a generic termination path, reducing the risk of persistence corruption during update drains.
- DayZ Workshop content remains stored in instance-private managed storage, while the game process receives deterministic relative aliases instead of absolute `steam-workshop:<id>` paths.
- Linux privileged materialization creates and removes only instance-scoped DayZ aliases, preserves aliases belonging to other instances, and fails closed on unsafe collisions.
- `-mod` and `-serverMod` now reference the relative aliases projected for the instance, preventing the DayZ server browser metadata anomaly that exposed `sakhal` as content without a valid Workshop ID.
- DayZ profile migration and persistence tests are aligned with runtime profile version 10.

## Validation

- Live A/B validation on the Horizon hybrid host used the same DayZ binary, build, Chernarus mission, ports and CF/CodeLock/VPPAdminTools content while changing only the mod path representation.
- The production-style absolute `steam-workshop:<id>` arguments reproduced the unexpected `sakhal` entry in A2S_RULES.
- Relative aliases removed the unexpected `sakhal` entry while preserving all three Workshop mods and valid A2S responses.
- PR #722 passed CI, DayZ Native Restart, Universal Content Platform, Universal Content E2E, M8 Universal Mod Management, M10 Final E2E Release Validation, External Controller Agent E2E, Update Manager Regression and the Phase 22 final E2E gate.
- Relevant local DayZ/runtime/materialization regression suites passed before merge.
