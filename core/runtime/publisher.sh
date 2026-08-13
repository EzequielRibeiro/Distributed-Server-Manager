#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Server Publisher
#
# Responsável:
#
# Publicar estado atual do servidor
#
# Não conhece jogos.
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


source "${DSM_ROOT}/core/runtime/context.sh"


publish_server_state()
{
    load_game_runtime || return 1

    local STATE_DIR
    local INFO_JSON
    local HEALTH
    local STATUS
    local PID
    local CPU
    local MEMORY
    local UPTIME
    local CHILDREN

    STATE_DIR="${DSM_ROOT}/runtime/state/$(runtime_host)/$(runtime_game)/$(runtime_instance)"

    mkdir -p "${STATE_DIR}"

    # =========================================================
    # Runtime Info
    # =========================================================

    INFO_JSON="$(runtime_info 2>/dev/null || true)"

    # Se runtime_info não retornar JSON válido,
    # utilizar estado offline seguro.
    if [[ -z "${INFO_JSON}" ]] || \
       ! jq -e . >/dev/null 2>&1 <<< "${INFO_JSON}"
    then

        INFO_JSON='{
          "status":"offline",
          "pid":0,
          "cpu":"0",
          "memory":"0",
          "uptime":"0",
          "children":"0"
        }'

    fi

    # =========================================================
    # Extrair informações
    # =========================================================

    STATUS="$(jq -r '.status // "offline"' <<< "${INFO_JSON}")"
    PID="$(jq -r '.pid // 0' <<< "${INFO_JSON}")"
    CPU="$(jq -r '.cpu // "0"' <<< "${INFO_JSON}")"
    MEMORY="$(jq -r '.memory // "0"' <<< "${INFO_JSON}")"
    UPTIME="$(jq -r '.uptime // "0"' <<< "${INFO_JSON}")"
    CHILDREN="$(jq -r '.children // "0"' <<< "${INFO_JSON}")"

    # =========================================================
    # Health
    # =========================================================

    if [[ "${STATUS}" == "online" ]]
    then
        if declare -F runtime_health >/dev/null &&
           runtime_health >/dev/null 2>&1
        then
            HEALTH="healthy"
        else
            HEALTH="unhealthy"
        fi
    else
        HEALTH="offline"
    fi

    # =========================================================
    # Publicar
    # =========================================================

    cat > "${STATE_DIR}/server.json" <<EOF
{
  "identity": {
    "host": "$(runtime_host)",
    "game": "$(runtime_game)",
    "instance": "$(runtime_instance)"
  },

  "server": {
    "status": "${STATUS}",
    "health": "${HEALTH}",
    "pid": ${PID}
  },

  "process": {
    "cpu": "${CPU}",
    "memory": "${MEMORY}",
    "uptime": "${UPTIME}",
    "children": "${CHILDREN}"
  },

  "timestamp": $(date +%s)
}
EOF

    local INSTANCE_METADATA
    INSTANCE_METADATA="$(get_instance_path)/.dsm/instance-metadata.json"
    if [[ -f "${INSTANCE_METADATA}" ]] && jq -e '
        type == "object" and
        (.controller_id | type == "string" and length > 0) and
        (.agent_id | type == "string" and length > 0) and
        ((.customer.id // .customer_id) | type == "string" and length > 0)
    ' "${INSTANCE_METADATA}" >/dev/null 2>&1
    then
        cp "${INSTANCE_METADATA}" "${STATE_DIR}/instance.json"
    else
        echo "Metadados obrigatórios ausentes: controller_id, agent_id e customer.id" >&2
        return 1
    fi
}


load_game_runtime()
{

    local GAME

    GAME="$(runtime_game | tr '[:upper:]' '[:lower:]')"


    local RUNTIME

    RUNTIME="${DSM_ROOT}/games/${GAME}/runtime.sh"


    if [[ ! -f "${RUNTIME}" ]]
    then
        echo "Runtime não encontrado:"
        echo "${RUNTIME}"

        return 1
    fi


    source "${RUNTIME}"

}

export -f publish_server_state


if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    publish_server_state
fi
