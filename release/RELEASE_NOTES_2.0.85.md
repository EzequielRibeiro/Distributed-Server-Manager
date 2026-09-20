# Capivara DSM 2.0.85

Minecraft Java network contract hotfix.

## RCON port application

Fixes customer Minecraft Java instance creation failing with:

`network ports are reserved but not applied: rcon`

All published Minecraft Java runtimes that reserve an RCON role now explicitly apply the reserved port to `server.properties` using:

- `enable-rcon=true`
- `rcon.port={rcon}`
- `broadcast-rcon-to-ops=false`

The existing `server-port={game}` application remains unchanged.

## Coverage

The fix applies to Vanilla, Paper, Purpur, Fabric, Forge, NeoForge, Quilt, Folia, Arclight, SpongeVanilla and Youer.

## Validation

Adds a regression gate that rejects published Minecraft Java runtimes which reserve an RCON role without applying it.
