#!/usr/bin/env bash
# =============================================================
# DSM Resource Identity Library
#
# Responsável:
#   - Resolver identidade de recursos DSM
#   - Validar Server / Game / Instance
#   - Carregar configuração de recursos
#
# Modelo:
#
#   SERVER
#      |
#      +-- GAME
#             |
#             +-- INSTANCE
#
# Exemplo:
#
#   server01 / dayz / survival01
#
# =============================================================


set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


RESOURCE_CONFIG="${RESOURCE_CONFIG:-$DSM_ROOT/config/resources.json}"



# =============================================================
# Verifica configuração
# =============================================================

resource_exists()
{

    if [ ! -f "$RESOURCE_CONFIG" ]
    then
        return 1
    fi

}



# =============================================================
# Lista servidores
# =============================================================

resource_servers()
{

    resource_exists || return 1


    jq -r '
    .servers[].id
    ' \
    "$RESOURCE_CONFIG"

}



# =============================================================
# Lista jogos de um servidor
#
# Uso:
# resource_games server01
#
# =============================================================

resource_games()
{

    local SERVER="$1"


    resource_exists || return 1


    jq -r \
    --arg server "$SERVER" '

    .servers[]
    | select(.id==$server)
    | .games[].id

    ' \
    "$RESOURCE_CONFIG"

}



# =============================================================
# Lista instâncias
#
# Uso:
# resource_instances server01 dayz
#
# =============================================================

resource_instances()
{

    local SERVER="$1"
    local GAME="$2"


    resource_exists || return 1


    jq -r \
    --arg server "$SERVER" \
    --arg game "$GAME" '

    .servers[]
    | select(.id==$server)
    | .games[]
    | select(.id==$game)
    | .instances[].id

    ' \
    "$RESOURCE_CONFIG"

}



# =============================================================
# Busca recurso completo
#
# Uso:
#
# resource_get server01 dayz survival01
#
# Retorna JSON
#
# =============================================================

resource_get()
{

    local SERVER="$1"
    local GAME="$2"
    local INSTANCE="$3"


    resource_exists || return 1


    jq \
    --arg server "$SERVER" \
    --arg game "$GAME" \
    --arg instance "$INSTANCE" '

    .servers[]
    | select(.id==$server)

    | {
        server:.id,
        host:.host,
        game:
        (
            .games[]
            | select(.id==$game)
        )
    }

    | .game.instances[]
    | select(.id==$instance)

    | {
        server:$server,
        game:$game,
        instance:.id,
        path:.path,
        port:.port
    }

    ' \
    "$RESOURCE_CONFIG"

}



# =============================================================
# Validação
#
# Retorna:
# 0 = válido
# 1 = inválido
#
# =============================================================

resource_validate()
{

    local SERVER="$1"
    local GAME="$2"
    local INSTANCE="$3"


    resource_get \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE" \
    >/dev/null


}



# =============================================================
# Exporta contexto do recurso
#
# Usado pelos workers
#
# =============================================================

resource_export()
{

    local SERVER="$1"
    local GAME="$2"
    local INSTANCE="$3"


    export DSM_SERVER="$SERVER"
    export DSM_GAME="$GAME"
    export DSM_INSTANCE="$INSTANCE"


}



# =============================================================
# Mostra identidade atual
# =============================================================

resource_identity()
{

cat <<EOF
{
  "server":"${DSM_SERVER:-}",
  "game":"${DSM_GAME:-}",
  "instance":"${DSM_INSTANCE:-}"
}
EOF

}