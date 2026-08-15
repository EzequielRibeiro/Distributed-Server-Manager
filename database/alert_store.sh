#!/usr/bin/env bash

set -euo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_DATABASE="${DSM_DATABASE:-${DSM_ROOT}/data/capivara.db}"

SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &&
    pwd
)"

ALERT_CLI="${SCRIPT_DIR}/alert_cli.py"

PYTHON_BIN="${PYTHON_BIN:-python3}"


json_error()
{
    local message="${1:-unknown error}"

    "$PYTHON_BIN" - "$message" <<'PY'
import json
import sys

print(
    json.dumps(
        {
            "ok": False,
            "error": sys.argv[1],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
)
PY
}


require_cli()
{
    if [[ ! -f "$ALERT_CLI" ]]
    then
        json_error \
            "Alert Store CLI not found: ${ALERT_CLI}"
        exit 2
    fi
}


run_cli()
{
    require_cli

    DSM_ROOT="$DSM_ROOT" \
    DSM_DATABASE="$DSM_DATABASE" \
    "$PYTHON_BIN" \
        "$ALERT_CLI" \
        "$@"
}


normalize_level()
{
    local level="${1:-INFO}"

    case "${level^^}" in
        INFO)
            printf '%s\n' "INFO"
            ;;

        WARNING|WARN)
            printf '%s\n' "WARNING"
            ;;

        CRITICAL|ERROR|FATAL)
            printf '%s\n' "CRITICAL"
            ;;

        SUCCESS|OK)
            printf '%s\n' "INFO"
            ;;

        *)
            printf '%s\n' "$level"
            ;;
    esac
}


command_open()
{
    local id="${1:-}"
    local level="${2:-}"
    local title="${3:-}"
    local message="${4:-}"
    local controller_id="${5:-}"
    local rule_id="${6:-}"

    if [[ -z "$id" ]]
    then
        json_error "id is required"
        return 2
    fi

    if [[ -z "$level" ]]
    then
        json_error "level is required"
        return 2
    fi

    if [[ -z "$message" ]]
    then
        json_error "message is required"
        return 2
    fi

    if [[ -z "$controller_id" ]]
    then
        json_error "controller_id is required"
        return 2
    fi

    if [[ -z "$rule_id" ]]
    then
        rule_id="legacy.${id}"
    fi

    level="$(
        normalize_level "$level"
    )"

    if [[ -n "$title" ]]
    then
        message="${title}: ${message}"
    fi

    run_cli \
        open \
        --id "$id" \
        --rule-id "$rule_id" \
        --level "$level" \
        --message "$message" \
        --scope controller \
        --controller-id "$controller_id"
}


command_ack()
{
    local id="${1:-}"

    if [[ -z "$id" ]]
    then
        json_error "id is required"
        return 2
    fi

    run_cli \
        ack \
        "$id"
}


command_resolve()
{
    local id="${1:-}"

    if [[ -z "$id" ]]
    then
        json_error "id is required"
        return 2
    fi

    run_cli \
        resolve \
        "$id"
}


command_active()
{
    run_cli active
}


command_count()
{
    run_cli count
}


command_history()
{
    local id="${1:-}"

    if [[ -n "$id" ]]
    then
        run_cli \
            history \
            "$id"
    else
        run_cli history
    fi
}


usage()
{
    cat <<'EOF'
Capivara DSM Alert Store Shell Adapter

Uso:

  alert_store.sh open \
      <id> \
      <level> \
      <title> \
      <message> \
      <controller_id> \
      [rule_id]

  alert_store.sh ack <id>

  alert_store.sh resolve <id>

  alert_store.sh active

  alert_store.sh count

  alert_store.sh history [id]


Niveis aceitos pelo adaptador:

  INFO
  WARNING
  WARN
  CRITICAL
  ERROR
  FATAL
  SUCCESS
  OK


Normalizacao:

  WARN       -> WARNING
  ERROR      -> CRITICAL
  FATAL      -> CRITICAL
  SUCCESS    -> INFO
  OK         -> INFO
EOF
}


main()
{
    local command="${1:-help}"

    if [[ $# -gt 0 ]]
    then
        shift
    fi

    case "$command" in
        open|create|push)
            command_open "$@"
            ;;

        ack|acknowledge)
            command_ack "$@"
            ;;

        resolve)
            command_resolve "$@"
            ;;

        active|list)
            command_active
            ;;

        count)
            command_count
            ;;

        history)
            command_history "$@"
            ;;

        help|--help|-h|"")
            usage
            ;;

        *)
            json_error \
                "invalid action: ${command}"
            return 2
            ;;
    esac
}


main "$@"