# Capivara DSM 2.0.110

## Minecraft Java native console input

Minecraft Java instances now support an Agent-local native stdin console transport.

### Improvements

- Adds a supervised stdin bridge for managed Minecraft Java processes.
- Adds a per-instance Unix console socket.
- Native console commands prefer the `minecraft-stdin` transport.
- Existing instances without the native socket retain `minecraft-rcon` as a compatibility fallback.
- stdout/stderr continue through systemd journal and the existing real-time console stream.
- Non-Minecraft runtimes remain unchanged.

### Why

Some Bukkit plugins, including LuckPerms, execute commands asynchronously.

On Youer, RCON can return before those asynchronous commands emit their response, causing valid commands to appear to return an empty result.

The native stdin console path sends commands through the server's normal console input while preserving the existing journal-based output path.

### Validation

- Native Unix socket command delivery verified.
- Child stdin delivery verified.
- stdout inheritance verified.
- Socket cleanup verified.
- stdin-first / RCON-fallback transport selection verified.
- Minecraft Java-only materialization verified.
- 46 targeted regression tests passed before merge.
- PR #764 passed all 27 GitHub checks.
