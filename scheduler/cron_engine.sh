#!/bin/bash
# =============================================================
# DSM Cron Engine
#
# Arquivo:
#   scheduler/cron_engine.sh
#
# Responsável:
#   Interpretar schedules DSM
#
# DSM Version:
#   1.2.2
#
# Correções:
#   - Validação de schedule
#   - Próxima execução
#   - Suporte @daily/@every
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

LOG_MODULE="scheduler"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
cron_log()
{
    local MSG="$1"

    mkdir -p "${DSM_ROOT}/logs"

    echo \
"$(date '+%Y-%m-%d %H:%M:%S') - $MSG" \
>> "${DSM_ROOT}/logs/cron_engine.log"
}

# -------------------------------------------------------------
# Validar horário HH:MM
#
# Retorno:
# 0 válido
# 1 inválido
# -------------------------------------------------------------
cron_validate_time()
{
    local TIME="$1"

    if ! [[ "$TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]
    then
        return 1
    fi

    return 0
}

# -------------------------------------------------------------
# Validar schedule DSM
#
# Exemplos:
#
# 04:00
# @daily
# @every:60
#
# -------------------------------------------------------------
cron_validate()
{
    local SCHEDULE="$1"

    if [ -z "$SCHEDULE" ]
    then
        return 1
    fi

    case "$SCHEDULE" in
        @daily)
            return 0
        ;;
        @hourly)
            return 0
        ;;
        @weekly)
            return 0
        ;;
        @monthly)
            return 0
        ;;
        @every:*)
            local VALUE
            VALUE="${SCHEDULE#@every:}"

            if ! [[ "$VALUE" =~ ^[0-9]+$ ]]
            then
                return 1
            fi

            if [ "$VALUE" -le 0 ]
            then
                return 1
            fi

            return 0
        ;;
        *)
            cron_validate_time "$SCHEDULE"
            return $?
        ;;
    esac
}

# -------------------------------------------------------------
# Converter schedule para segundos
# -------------------------------------------------------------
cron_to_seconds()
{
    local SCHEDULE="$1"

    case "$SCHEDULE" in
        @hourly)
            echo 3600
        ;;
        @daily)
            echo 86400
        ;;
        @weekly)
            echo 604800
        ;;
        @monthly)
            echo 2592000
        ;;
        @every:*)
            echo "${SCHEDULE#@every:}"
        ;;
        *)
            echo 0
        ;;
    esac
}

# -------------------------------------------------------------
# Próxima execução
#
# Retorna timestamp Unix
#
# -------------------------------------------------------------
cron_next_run()
{
    local SCHEDULE="$1"

    if ! cron_validate "$SCHEDULE"
    then
        cron_log \
        "Schedule inválido: $SCHEDULE"
        return 1
    fi

    case "$SCHEDULE" in
        @every:*)
            local SEC
            SEC=$(cron_to_seconds "$SCHEDULE")

            echo \
            $(( $(date +%s) + SEC ))
        ;;
        @hourly)
            date \
            -d "next hour" \
            +%s
        ;;
        @daily)
            date \
            -d "tomorrow 00:00" \
            +%s
        ;;
        @weekly)
            date \
            -d "next monday 00:00" \
            +%s
        ;;
        @monthly)
            date \
            -d "next month 00:00" \
            +%s
        ;;
        *)
            local HOUR
            local MIN

            HOUR="${SCHEDULE%:*}"
            MIN="${SCHEDULE#*:}"

            local TODAY

            TODAY=$(date \
            -d "today ${HOUR}:${MIN}" \
            +%s)

            if [ "$TODAY" -le "$(date +%s)" ]
            then
                TODAY=$(date \
                -d "tomorrow ${HOUR}:${MIN}" \
                +%s)
            fi

            echo "$TODAY"
        ;;
    esac
}

# -------------------------------------------------------------
# Verificar execução
#
# Retorno:
# 0 deve executar
#
# -------------------------------------------------------------
cron_match()
{
    local SCHEDULE="$1"

    if ! cron_validate "$SCHEDULE"
    then
        return 1
    fi

    case "$SCHEDULE" in

        @every:*)
            #
            # A execução periódica precisa de estado persistente.
            # cron_match isoladamente não deve considerar
            # "agora + intervalo" como vencido.
            #
            return 1
        ;;

        @hourly)
            #
            # Scheduler roda aproximadamente uma vez por minuto.
            # Executa no minuto 00.
            #
            [[ "$(date +%M)" == "00" ]]
            return
        ;;

        @daily)
            #
            # Uma vez ao dia, à meia-noite.
            #
            [[ "$(date +%H:%M)" == "00:00" ]]
            return
        ;;

        @weekly)
            #
            # Segunda-feira à meia-noite.
            #
            [[ "$(date +%u)" == "1" ]] &&
            [[ "$(date +%H:%M)" == "00:00" ]]
            return
        ;;

        @monthly)
            #
            # Primeiro dia do mês à meia-noite.
            #
            [[ "$(date +%d)" == "01" ]] &&
            [[ "$(date +%H:%M)" == "00:00" ]]
            return
        ;;

        *)
            #
            # HH:MM
            #
            # Deve executar somente quando o relógio atual
            # coincide com o horário configurado.
            #
            [[ "$(date +%H:%M)" == "$SCHEDULE" ]]
            return
        ;;
    esac
}

# -------------------------------------------------------------
# Mostrar próxima execução formatada
# -------------------------------------------------------------
cron_next_format()
{
    local TS
    TS=$(cron_next_run "$1")

    if [ -z "$TS" ]
    then
        echo "inválido"
        return 1
    fi

    date \
    -d "@$TS" \
    '+%Y-%m-%d %H:%M:%S'
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
case "$1" in
validate)
cron_validate "$2"
;;
next)
cron_next_run "$2"
;;
next-format)
cron_next_format "$2"
;;
*)
cat <<EOF
DSM Cron Engine

Uso:
cron_engine.sh validate SCHEDULE
cron_engine.sh next SCHEDULE
cron_engine.sh next-format SCHEDULE

Exemplos:
cron_engine.sh validate 04:00
cron_engine.sh validate @daily
cron_engine.sh validate @every:300
EOF
;;
esac
fi
