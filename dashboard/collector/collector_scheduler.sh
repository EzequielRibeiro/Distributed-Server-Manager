#!/bin/bash
# =============================================================
# DSM Dashboard Scheduler Collector
#
# Arquivo:
#   dashboard/collector/collector_scheduler.sh
#
# Responsável:
#   Coletar informações do Scheduler para Dashboard
#
# DSM Version:
#   1.3.0
#
# Scheduler:
#   1.2.2
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


SCHEDULER_DIR="${DSM_ROOT}/scheduler"


STATE_DIR="${DSM_ROOT}/dashboard/state"


STATE_FILE="${STATE_DIR}/scheduler_state.json"



JOBS_DB="${SCHEDULER_DIR}/jobs.db"


HISTORY_FILE="${DSM_ROOT}/logs/scheduler_history.log"




# -------------------------------------------------------------
# Dependências
# -------------------------------------------------------------

command_exists()
{

    command -v "$1" >/dev/null 2>&1

}





# -------------------------------------------------------------
# Inicializar estado
# -------------------------------------------------------------

init_state()
{

    mkdir -p "$STATE_DIR"


}





# -------------------------------------------------------------
# Última execução
# -------------------------------------------------------------

get_last_execution()
{

    if [ ! -f "$HISTORY_FILE" ]

    then

        echo null

        return

    fi



    tail -1 "$HISTORY_FILE" |

    sed \
    's/^\[\(.*\)\].*/\1/' |

    jq -R .

}





# -------------------------------------------------------------
# Carregar jobs
# -------------------------------------------------------------

collect_jobs()
{

    if [ ! -f "$JOBS_DB" ]

    then

        echo '[]'

        return

    fi



    jq \
    '.jobs // []' \
    "$JOBS_DB"

}





# -------------------------------------------------------------
# Contadores
# -------------------------------------------------------------

count_jobs()
{

    if [ ! -f "$JOBS_DB" ]

    then

        echo 0

        return

    fi



    jq \
    '.jobs | length' \
    "$JOBS_DB"

}





count_enabled()
{

    if [ ! -f "$JOBS_DB" ]

    then

        echo 0

        return

    fi



    jq \
    '[.jobs[] | select(.enabled==1 or .enabled==true)] | length' \
    "$JOBS_DB"

}





# -------------------------------------------------------------
# Próxima execução
# -------------------------------------------------------------

next_execution()
{

    local SCHEDULE="$1"



    if [ -x "${SCHEDULER_DIR}/cron_engine.sh" ]

    then


        "${SCHEDULER_DIR}/cron_engine.sh" \
        next-format \
        "$SCHEDULE"



    else

        echo null

    fi

}





# -------------------------------------------------------------
# Criar lista resumida
# -------------------------------------------------------------

collect_jobs_summary()
{

    if [ ! -f "$JOBS_DB" ]

    then

        echo '[]'

        return

    fi





    jq -c '.jobs[]' "$JOBS_DB" |

    while read JOB

    do


        NAME=$(echo "$JOB" | jq -r '.name')

        SCHEDULE=$(echo "$JOB" | jq -r '.schedule')

        ENABLED=$(echo "$JOB" | jq -r '.enabled')



        NEXT=$(next_execution "$SCHEDULE")



        jq -n \
        --arg name "$NAME" \
        --arg schedule "$SCHEDULE" \
        --arg next "$NEXT" \
        --argjson enabled "$ENABLED" '

        {

            name:$name,

            schedule:$schedule,

            enabled:$enabled,

            next_run:$next

        }

        '


    done |

    jq -s .

}





# -------------------------------------------------------------
# Coleta principal
# -------------------------------------------------------------

collect_scheduler()
{


    init_state



    local TOTAL

    local ACTIVE



    TOTAL=$(count_jobs)


    ACTIVE=$(count_enabled)





    LAST=$(get_last_execution)





    JOBS=$(collect_jobs_summary)





    jq -n \
    --argjson total "$TOTAL" \
    --argjson active "$ACTIVE" \
    --argjson last "$LAST" \
    --argjson jobs "$JOBS" '

    {

        module:"scheduler",

        status:"ONLINE",

        updated_at:(now|todate),


        jobs_total:$total,

        jobs_active:$active,


        last_execution:$last,


        jobs:$jobs

    }

    ' > "$STATE_FILE"



}





# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in


run)

collect_scheduler

;;


status)

cat "$STATE_FILE"

;;


*)

cat <<EOF

DSM Scheduler Collector


Uso:


collector_scheduler.sh run


collector_scheduler.sh status


EOF

;;


esac
