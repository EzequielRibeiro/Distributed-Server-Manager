#!/bin/bash
# =============================================================
# DSM Cron Engine
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
LOG_MODULE="scheduler"

cron_log()
{
    local MSG="$1"
    mkdir -p "${DSM_ROOT}/logs"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $MSG" >> "${DSM_ROOT}/logs/cron_engine.log"
}

cron_validate_time()
{
    local TIME="$1"
    [[ "$TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]
}

cron_validate_timezone()
{
    local TIMEZONE="${1:-UTC}"
    [[ -n "${TIMEZONE}" ]] || return 1
    [[ "${TIMEZONE}" =~ ^[A-Za-z0-9._+-]+(/[A-Za-z0-9._+-]+)*$ ]] || return 1
    [[ "${TIMEZONE}" == "UTC" || "${TIMEZONE}" == "Etc/UTC" || -f "/usr/share/zoneinfo/${TIMEZONE}" ]]
}

cron_validate()
{
    local SCHEDULE="$1"
    if [ -z "$SCHEDULE" ]; then return 1; fi
    case "$SCHEDULE" in
        @daily|@hourly|@weekly|@monthly) return 0 ;;
        @every:*)
            local VALUE="${SCHEDULE#@every:}"
            [[ "$VALUE" =~ ^[0-9]+$ ]] && [ "$VALUE" -gt 0 ]
            return $?
        ;;
        *) cron_validate_time "$SCHEDULE" ;;
    esac
}

cron_to_seconds()
{
    local SCHEDULE="$1"
    case "$SCHEDULE" in
        @hourly) echo 3600 ;;
        @daily) echo 86400 ;;
        @weekly) echo 604800 ;;
        @monthly) echo 2592000 ;;
        @every:*) echo "${SCHEDULE#@every:}" ;;
        *) echo 0 ;;
    esac
}

cron_next_run()
{
    local SCHEDULE="$1" TIMEZONE="${2:-UTC}"
    if ! cron_validate "$SCHEDULE"; then cron_log "Schedule inválido: $SCHEDULE"; return 1; fi
    if ! cron_validate_timezone "$TIMEZONE"; then cron_log "Timezone inválido: $TIMEZONE"; return 1; fi

    case "$SCHEDULE" in
        @every:*)
            local SEC; SEC=$(cron_to_seconds "$SCHEDULE")
            echo $(( $(date +%s) + SEC ))
        ;;
        @hourly) TZ="$TIMEZONE" date -d "next hour" +%s ;;
        @daily) TZ="$TIMEZONE" date -d "tomorrow 00:00" +%s ;;
        @weekly) TZ="$TIMEZONE" date -d "next monday 00:00" +%s ;;
        @monthly) TZ="$TIMEZONE" date -d "next month 00:00" +%s ;;
        *)
            local HOUR MIN TODAY
            HOUR="${SCHEDULE%:*}"; MIN="${SCHEDULE#*:}"
            TODAY=$(TZ="$TIMEZONE" date -d "today ${HOUR}:${MIN}" +%s)
            if [ "$TODAY" -le "$(date +%s)" ]; then
                TODAY=$(TZ="$TIMEZONE" date -d "tomorrow ${HOUR}:${MIN}" +%s)
            fi
            echo "$TODAY"
        ;;
    esac
}

cron_match()
{
    local SCHEDULE="$1" TIMEZONE="${2:-UTC}"
    cron_validate "$SCHEDULE" || return 1
    cron_validate_timezone "$TIMEZONE" || return 1

    case "$SCHEDULE" in
        @every:*) return 1 ;;
        @hourly) [[ "$(TZ="$TIMEZONE" date +%M)" == "00" ]] ;;
        @daily) [[ "$(TZ="$TIMEZONE" date +%H:%M)" == "00:00" ]] ;;
        @weekly)
            [[ "$(TZ="$TIMEZONE" date +%u)" == "1" ]] &&
            [[ "$(TZ="$TIMEZONE" date +%H:%M)" == "00:00" ]]
        ;;
        @monthly)
            [[ "$(TZ="$TIMEZONE" date +%d)" == "01" ]] &&
            [[ "$(TZ="$TIMEZONE" date +%H:%M)" == "00:00" ]]
        ;;
        *) [[ "$(TZ="$TIMEZONE" date +%H:%M)" == "$SCHEDULE" ]] ;;
    esac
}

cron_next_format()
{
    local TS TIMEZONE="${2:-UTC}"
    TS=$(cron_next_run "$1" "$TIMEZONE") || return 1
    if [ -z "$TS" ]; then echo "inválido"; return 1; fi
    TZ="$TIMEZONE" date -d "@$TS" '+%Y-%m-%d %H:%M:%S %Z'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
case "${1:-}" in
validate)
cron_validate "${2:-}" && cron_validate_timezone "${3:-UTC}"
;;
next)
cron_next_run "${2:-}" "${3:-UTC}"
;;
next-format)
cron_next_format "${2:-}" "${3:-UTC}"
;;
*)
cat <<EOF
DSM Cron Engine

Uso:
cron_engine.sh validate SCHEDULE [TIMEZONE]
cron_engine.sh next SCHEDULE [TIMEZONE]
cron_engine.sh next-format SCHEDULE [TIMEZONE]

Exemplos:
cron_engine.sh validate 04:00 America/Sao_Paulo
cron_engine.sh next-format @daily Europe/Lisbon
cron_engine.sh validate @every:300 UTC
EOF
;;
esac
fi
