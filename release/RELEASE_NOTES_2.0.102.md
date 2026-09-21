# Capivara DSM 2.0.102

Minecraft Java game-data artifact preservation hotfix.

## Fix

- HTTP artifacts declared as `artifact_mode=file`, `java`, or `jar` are now preserved as files instead of being auto-expanded merely because JAR files use ZIP container format.
- Fixes Minecraft Java Youer provisioning where the downloaded `server.jar` was unpacked into `META-INF`, `com`, `data`, `versions`, etc., removing the declared executable and causing `game-data integrity check failed: degraded` during `install_content`.
- Linux and Windows Agent game-data executors use the same preservation rule.
- Explicit archive contracts remain extractable; `http-archive`/declared archive behavior is not removed.

## Validation

- Failure reproduced with installed v2.0.101 using the exact current Youer RuntimeSelection (1.21.1 build 914): integrity reported `degraded`, `executable_present=false`, and the target contained extracted JAR contents but no `server.jar`.
- Patched executor with the same live artifact produced `integrity.health=ok`, `executable_present=true`, `executable_ready=true`, and a 123 MiB `server.jar`.
- PR #737 passed all 24 triggered workflows, including CI, Agent Game Data, Windows Agent Parity, External Controller Agent E2E and M10 Final E2E Release Validation.
