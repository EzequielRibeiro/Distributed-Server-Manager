#!/bin/sh
#
# Runtime State
#

runtime_state_init()
{
    mkdir -p "$RUNTIME_DIR/state"

    [ -f "$RUNTIME_DIR/state/runtime.json" ] || \
        echo '{}' > "$RUNTIME_DIR/state/runtime.json"

    [ -f "$RUNTIME_DIR/state/games.json" ] || \
        echo '[]' > "$RUNTIME_DIR/state/games.json"

    [ -f "$RUNTIME_DIR/state/servers.json" ] || \
        echo '[]' > "$RUNTIME_DIR/state/servers.json"
}