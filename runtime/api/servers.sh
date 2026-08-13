#!/bin/bash

#
#API para Dashboard listar servidores.
#


DSM_ROOT="/opt/dsm"

REGISTRY="$DSM_ROOT/runtime/registry/servers.json"


case "$1" in


list)

    jq . "$REGISTRY"

;;


get)

    ID="$2"

    jq \
    --arg id "$ID" \
    '
    .servers[]
    | select(.id==$id)
    ' \
    "$REGISTRY"

;;


*)

echo "
Uso:

servers.sh list
servers.sh get server01

"

;;

esac