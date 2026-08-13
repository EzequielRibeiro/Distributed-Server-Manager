#!/usr/bin/env bash
# =============================================================
# DSM Dashboard Metrics Worker
#
# Engine:
#   dashboard/api/metrics.sh
#
# Output:
#   dashboard/state/metrics_state.json
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
source "$DSM_ROOT/core/runtime_context.sh"
source "$DSM_ROOT/core/runtime_engine.sh"

DSM_INTERVAL="${DSM_INTERVAL:-5}"

LOG_DIR="${DSM_ROOT}/logs"

LOG="${LOG_DIR}/metrics_worker.log"

API_SCRIPT="${DSM_ROOT}/dashboard/api/metrics.sh"

mkdir -p "${LOG_DIR}"


log()
{
    echo "$(date '+%F %T') $*" >> "${LOG}"
}


collect_metrics()
{
    if [ ! -x "${API_SCRIPT}" ]
    then
        log "ERRO: Metrics API não encontrada: ${API_SCRIPT}"
        return 1
    fi

    local JSON

    if ! JSON="$("${API_SCRIPT}")"
    then
        log "ERRO executando Metrics API"
        return 1
    fi

    if [ -z "${JSON}" ]
    then
        log "ERRO: resposta vazia da API"
        return 1
    fi

    if ! jq empty >/dev/null 2>&1 <<< "${JSON}"
    then
        log "ERRO: JSON inválido"
        return 1
    fi

    JSON=$(jq '
    def num:
        if . == null then 0
        elif type == "string" then tonumber
        else .
        end;

    .cpu.process_pct |= num |
    .cpu.host_pct |= num |
    .cpu.cores |= num |
    .memory.total_mb |= num |
    .memory.used_mb |= num |
    .memory.available_mb |= num |
    .memory.free_pct |= num |
    .memory.dayz_mb |= num |
    .memory.dayz_pct |= num |
    .disk.total_gb |= num |
    .disk.used_gb |= num |
    .disk.free_gb |= num |
    .disk.percent |= num |
    . + {
        scope: "node",
        updated_at: now
    }
    ' <<< "${JSON}")

    local DATABASE="${DSM_ROOT}/data/capivara.db"

    if [[ ! -s "${DATABASE}" ]]
    then
        log "ERRO: banco Capivara não encontrado: ${DATABASE}"
        return 1
    fi

    local COUNT=0

    while IFS='|' read -r INSTANCE_ID NODE_ID GAME_ID AGENT_ID
    do
        [[ -n "${INSTANCE_ID}" ]] || continue
        [[ -n "${NODE_ID}" ]] || continue
        [[ -n "${GAME_ID}" ]] || continue

        local INSTANCE_JSON
        local INSTANCE_DIR
        local PID=""
        local CPU="0"
        local RSS_KB="0"
        local MEMORY_MB="0"
        local ELAPSED=""

        INSTANCE_DIR="${DSM_ROOT}/instances/${NODE_ID}/${GAME_ID}/${INSTANCE_ID}"

        local PIDFILE

        PIDFILE="${INSTANCE_DIR}/runtime/process.pid"

        if [[ -s "${PIDFILE}" ]]
        then
            PID="$(tr -dc '0-9' < "${PIDFILE}")"

            if [[ -z "${PID}" || ! -r "/proc/${PID}/stat" ]]
            then
                PID=""
            fi
        fi

        if [[ -z "${PID}" ]]
        then
            PID="$(
                pgrep -fo "${INSTANCE_DIR}/" 2>/dev/null || true
            )"
        fi

        if [[ -n "${PID}" && -r "/proc/${PID}/stat" ]]
        then
            CPU="$(
                ps -p "${PID}" -o pcpu= 2>/dev/null |
                xargs || echo 0
            )"

            RSS_KB="$(
                ps -p "${PID}" -o rss= 2>/dev/null |
                xargs || echo 0
            )"

            ELAPSED="$(
                ps -p "${PID}" -o etime= 2>/dev/null |
                xargs || true
            )"

            MEMORY_MB="$(
                awk -v kb="${RSS_KB:-0}"                     'BEGIN { printf "%.1f", kb / 1024 }'
            )"
        fi

        INSTANCE_JSON="$(
            jq -c \
                --arg node "${NODE_ID}" \
                --arg game "${GAME_ID}" \
                --arg instance "${INSTANCE_ID}" \
                --arg agent "${AGENT_ID}" \
                --arg pid "${PID:-}" \
                --arg cpu "${CPU:-0}" \
                --arg memory "${MEMORY_MB:-0}" \
                --arg elapsed "${ELAPSED:-}" \
                '
                . + {
                    identity: {
                        node: $node,
                        game: $game,
                        instance: $instance,
                        agent_id: $agent
                    },
                    instance: {
                        pid: (
                            if $pid == ""
                            then null
                            else ($pid | tonumber)
                            end
                        ),
                        cpu_pct: (
                            $cpu | tonumber? // 0
                        ),
                        memory_mb: (
                            $memory | tonumber? // 0
                        ),
                        uptime: (
                            if $elapsed == ""
                            then null
                            else $elapsed
                            end
                        )
                    }
                }
                ' <<< "${JSON}"
        )"

        runtime_update_resource \
            "${NODE_ID}" \
            "${GAME_ID}" \
            "${INSTANCE_ID}" \
            "metrics" \
            "${INSTANCE_JSON}"

        log "Metrics publicadas: ${NODE_ID}/${GAME_ID}/${INSTANCE_ID}"

        COUNT=$((COUNT + 1))

    done < <(
        sqlite3 "${DATABASE}" \
        "SELECT id,node_id,game_id,agent_id
         FROM instances
         WHERE node_id IS NOT NULL
           AND game_id IS NOT NULL
         ORDER BY node_id,game_id,id;"
    )

    log "Metrics publicadas para ${COUNT} instância(s)"

    return 0
}

main()
{

    log "DSM Metrics Worker iniciado"


    while true
    do

        collect_metrics || true

        sleep "${DSM_INTERVAL}"

    done

}


main