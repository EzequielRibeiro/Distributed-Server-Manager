#!/bin/bash
# =============================================================
# DSM Alert Engine v1.2.0
#
# Arquivo | File: monitor/alert_engine.sh
# Função | Function: Orquestrador principal do sistema de alertas | Main alert system orchestrator
# Execução | Execution: daemon systemd
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
CONFIG="$DSM_ROOT/config/alerts.conf"

# -------------------------------------------------------------
# Carregar configuração | Load configuration
# -------------------------------------------------------------
if [ -f "$CONFIG" ]; then
    source "$CONFIG"
else
    echo "Configuração não encontrada | Configuration not found:"
    echo "$CONFIG"
    exit 1
fi

# -------------------------------------------------------------
# Módulos DSM | DSM Modules
# -------------------------------------------------------------
METRICS_DIR="$DSM_ROOT/monitor/metrics"
MONITOR_DIR="$DSM_ROOT/monitor"

source "$MONITOR_DIR/alert_rules.sh"
source "$DSM_ROOT/core/alert_db.sh"
source "$DSM_ROOT/core/alert_history.sh"

# Process Engine
# Necessário para determinar o estado real de cada instância.
source "$DSM_ROOT/core/process/pid.sh"
source "$DSM_ROOT/core/process/tree.sh"
source "$DSM_ROOT/core/process/process.sh"

# DSM Metrics Engine
# Os coletores são módulos de funções e devem ser carregados via source.
source "$METRICS_DIR/metrics.sh"


LOG_FILE="${ALERT_LOG_FILE:-/opt/dsm/runtime/alerts/engine.log}"

# -------------------------------------------------------------
# Log interno | Internal log
# -------------------------------------------------------------
engine_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "$(date -Iseconds) | $*" >> "$LOG_FILE"
}

# -------------------------------------------------------------
# Cooldown
# -------------------------------------------------------------
cooldown_check()
{
    local id="$1"
    local file
    file="$DSM_ROOT/runtime/alerts/cooldown/$id"

    if [ -f "$file" ]; then
        local last
        last=$(cat "$file")
        local now
        now=$(date +%s)
        diff=$((now-last))

        if [ "$diff" -lt "$ALERT_COOLDOWN_SECONDS" ]
        then
            return 1
        fi
    fi

    mkdir -p "$(dirname "$file")"
    date +%s > "$file"

    return 0
}

# -------------------------------------------------------------
# Coleta métricas | Collect metrics
# -------------------------------------------------------------
collect_metrics()
{
    local INSTANCE_PATH="${1:-}"

    DAYZ_CPU=0
    HOST_CPU=0
    MEMORY=0
    DISK=0
    TEMP=0
    SERVER="OFFLINE"

    # CPU total do host
    if declare -F metrics_cpu_host_pct >/dev/null 2>&1; then
        HOST_CPU="$(
            metrics_cpu_host_pct 2>/dev/null ||
            echo 0
        )"
    fi

    # RAM usada do host
    if declare -F metrics_memory_free_pct >/dev/null 2>&1; then
        local MEMORY_FREE

        MEMORY_FREE="$(
            metrics_memory_free_pct 2>/dev/null ||
            echo 100
        )"

        MEMORY="$(
            awk -v free="${MEMORY_FREE:-100}" '
            BEGIN {
                used=100-free
                if (used < 0) used=0
                if (used > 100) used=100
                printf "%.0f", used
            }'
        )"
    fi

    # Espaço livre
    if declare -F metrics_disk_free_pct >/dev/null 2>&1; then
        DISK="$(
            metrics_disk_free_pct 2>/dev/null ||
            echo 0
        )"
    fi

    # Temperatura
    if declare -F metrics_temperature_cpu >/dev/null 2>&1; then
        TEMP="$(
            metrics_temperature_cpu 2>/dev/null ||
            echo 0
        )"
    fi

    #
    # Métricas da instância.
    #
    # Não procuramos mais DayZ por nome.
    # O PID pertence à própria instância.
    #
    if [[ -n "${INSTANCE_PATH}" ]] &&
       [[ -f "${INSTANCE_PATH}/instance.conf" ]]
    then
        if process_running "${INSTANCE_PATH}" >/dev/null 2>&1
        then
            SERVER="ONLINE"

            local PID=""

            PID="$(
                process_pid "${INSTANCE_PATH}" 2>/dev/null ||
                true
            )"

            if [[ "${PID}" =~ ^[0-9]+$ ]] &&
               [[ -r "/proc/${PID}/stat" ]]
            then
                DAYZ_CPU="$(
                    ps -p "${PID}" -o pcpu= 2>/dev/null |
                    xargs ||
                    echo 0
                )"
            fi
        fi
    fi

    # Normalização para regras inteiras
    DAYZ_CPU="${DAYZ_CPU%.*}"
    HOST_CPU="${HOST_CPU%.*}"
    MEMORY="${MEMORY%.*}"
    DISK="${DISK%.*}"
    TEMP="${TEMP%.*}"

    DAYZ_CPU="${DAYZ_CPU:-0}"
    HOST_CPU="${HOST_CPU:-0}"
    MEMORY="${MEMORY:-0}"
    DISK="${DISK:-0}"
    TEMP="${TEMP:-0}"
}


# -------------------------------------------------------------
# Executar avaliação | Run assessment
# -------------------------------------------------------------
engine_cycle()
{
    local DATABASE="${DSM_ROOT}/data/capivara.db"

    if [[ ! -s "${DATABASE}" ]]
    then
        engine_log \
            "ERRO: banco Capivara não encontrado: ${DATABASE}"
        return 1
    fi

    while IFS='|' read -r INSTANCE_ID NODE_ID GAME_ID AGENT_ID
    do
        [[ -n "${INSTANCE_ID}" ]] || continue
        [[ -n "${NODE_ID}" ]] || continue
        [[ -n "${GAME_ID}" ]] || continue

        local INSTANCE_PATH
        INSTANCE_PATH="${DSM_ROOT}/instances/${NODE_ID}/${GAME_ID}/${INSTANCE_ID}"

        #
        # Uma instância cadastrada pode ainda não ter sido
        # provisionada. Nesse caso registramos o fato e não
        # inventamos um runtime.
        #
        if [[ ! -f "${INSTANCE_PATH}/instance.conf" ]]
        then
            local PROVISION_FILE
            local PROVISION_STATUS
            local PROVISION_STAGE
            local PROVISION_PROGRESS

            PROVISION_FILE="${DSM_ROOT}/runtime/resources/${NODE_ID}/${GAME_ID}/${INSTANCE_ID}/provision.json"

            PROVISION_STATUS=""
            PROVISION_STAGE=""
            PROVISION_PROGRESS=""

            if [[ -s "${PROVISION_FILE}" ]]
            then
                PROVISION_STATUS="$(
                    jq -r '.status // ""' "${PROVISION_FILE}" 2>/dev/null ||
                    true
                )"

                PROVISION_STAGE="$(
                    jq -r '.stage // ""' "${PROVISION_FILE}" 2>/dev/null ||
                    true
                )"

                PROVISION_PROGRESS="$(
                    jq -r '.progress // 0' "${PROVISION_FILE}" 2>/dev/null ||
                    echo 0
                )"

                case "${PROVISION_STATUS}" in
                    pending_steam_auth|queued|pending|provisioning|installing|running)
                        engine_log \
                            "Instance=${NODE_ID}/${GAME_ID}/${INSTANCE_ID} PROVISIONING status=${PROVISION_STATUS} stage=${PROVISION_STAGE} progress=${PROVISION_PROGRESS}"
                        continue
                    ;;

                    failed|error)
                        engine_log \
                            "Instance=${NODE_ID}/${GAME_ID}/${INSTANCE_ID} PROVISION_FAILED status=${PROVISION_STATUS} stage=${PROVISION_STAGE} progress=${PROVISION_PROGRESS}"
                        continue
                    ;;

                    offline|completed|ready)
                        engine_log \
                            "Instance=${NODE_ID}/${GAME_ID}/${INSTANCE_ID} CONFIG_MISSING provision_status=${PROVISION_STATUS}"
                        continue
                    ;;
                esac
            fi

            engine_log \
                "Instance=${NODE_ID}/${GAME_ID}/${INSTANCE_ID} CONFIG_MISSING"

            continue
        fi

        collect_metrics "${INSTANCE_PATH}"

        engine_log \
            "Instance=${NODE_ID}/${GAME_ID}/${INSTANCE_ID} CPU_PROCESS=$DAYZ_CPU CPU_HOST=$HOST_CPU RAM=$MEMORY DISK=$DISK TEMP=$TEMP SERVER=$SERVER"

        evaluate_all \
            "$DAYZ_CPU" \
            "$HOST_CPU" \
            "$MEMORY" \
            "$DISK" \
            "$TEMP" \
            "$SERVER"

    done < <(
        sqlite3 "${DATABASE}" \
        "SELECT id,node_id,game_id,agent_id
         FROM instances
         WHERE node_id IS NOT NULL
           AND game_id IS NOT NULL
         ORDER BY node_id,game_id,id;"
    )
}


# -------------------------------------------------------------
# Modo daemon | Daemon mode
# -------------------------------------------------------------
daemon_loop()
{
    engine_log "DSM Alert Engine iniciado | started"
    while true
    do
        if [ "$ALERTS_ENABLED" = "true" ]
        then
            engine_cycle
        fi
        sleep "$ALERT_CHECK_INTERVAL"
    done
}

# -------------------------------------------------------------
# Execução manual | Manual execution
# -------------------------------------------------------------
case "$1" in
once)
    engine_cycle
;;
daemon)
    daemon_loop
;;
status)
echo "DSM Alert Engine"
echo
echo "Enabled | Ativado:"
echo "$ALERTS_ENABLED"
echo
echo "Interval | Intervalo:"
echo "$ALERT_CHECK_INTERVAL segundos | seconds"
;;
*)
cat <<EOF

DSM Alert Engine v1.2.0

Uso | Usage:

 alert_engine.sh once

   Executa uma avaliação | Runs an assessment

 alert_engine.sh daemon

   Executa modo serviço | Runs in service mode

 alert_engine.sh status

   Mostra configuração | Shows configuration

EOF
;;
esac
