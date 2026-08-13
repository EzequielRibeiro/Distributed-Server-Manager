#!/bin/sh
#
# Runtime Registry
#

runtime_registry_init()
{
    mkdir -p "$RUNTIME_DIR/state"
}

runtime_register_game()
{
    echo "$1"
}

runtime_register_server()
{
    echo "$1"
}

runtime_list_games()
{
    cat "$RUNTIME_DIR/state/games.json"
}

runtime_list_servers()
{
    cat "$RUNTIME_DIR/state/servers.json"
}