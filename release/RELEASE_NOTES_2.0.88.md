# Capivara DSM 2.0.88

Virtual runtime executable integrity hotfix.

## Minecraft Java integrity

Fixes provisioning failures after a successful Forge/NeoForge/Quilt installation where the Agent reported:

`game-data integrity check failed: degraded`

Catalog runtimes such as NeoForge declare `process.executable: @java`. This is a virtual runtime capability, not a file that should exist inside the game-data directory. Linux and Windows integrity checks now treat `@...` executables as external runtime capabilities while continuing to validate normal file-backed executables.

## Validation

Adds regression coverage ensuring installed directory-based Java runtimes with `@java` report `health=ok`.
