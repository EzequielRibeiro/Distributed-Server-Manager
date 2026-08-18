#!/usr/bin/env bash

# =============================================================
# Capivara DSM - Update Process Guard
#
# Responsabilidades:
# - detectar instâncias de jogos ainda em execução;
# - impedir atualização da árvore /opt/dsm enquanto houver
#   runtime de jogo ativo;
# - detectar workers legados do Dashboard executados fora
#   do controle atual do systemd.
#
# Este módulo NÃO encerra servidores de jogos.
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# =============================================================
# Helpers
# =============================================================

process_guard_instances_root()
{
    printf '%s\n' "${DSM_ROOT}/instances"
}


process_guard_instance_pidfiles()
{
    local instances_root

    instances_root="$(process_guard_instances_root)"

    [[ -d "${instances_root}" ]] || return 0

    find "${instances_root}" \
        -type f \
        \( \
            -path '*/runtime/process.pid' \
            -o -path '*/.dsm/runtime/process.pid' \
        \) \
        -print 2>/dev/null
}


process_guard_pid_is_running()
{
    local pid="${1:-}"

    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1

    (( pid > 0 )) || return 1

    kill -0 "${pid}" 2>/dev/null
}


process_guard_pid_command()
{
    local pid="${1:-}"

    process_guard_pid_is_running "${pid}" || return 1

    ps -p "${pid}" -o args= 2>/dev/null |
        sed 's/^[[:space:]]*//'
}


process_guard_instance_from_pidfile()
{
    local pidfile="${1:-}"
    local instance_path

    instance_path="${pidfile}"

    case "${instance_path}" in
        */.dsm/runtime/process.pid)
            instance_path="${instance_path%/.dsm/runtime/process.pid}"
            ;;
        */runtime/process.pid)
            instance_path="${instance_path%/runtime/process.pid}"
            ;;
        *)
            return 1
            ;;
    esac

    printf '%s\n' "${instance_path}"
}


# =============================================================
# Active game instances
# =============================================================

process_guard_active_instances()
{
    local pidfile
    local pid
    local instance_path
    local command

    while IFS= read -r pidfile
    do
        [[ -f "${pidfile}" ]] || continue

        pid="$(
            tr -d '[:space:]' <"${pidfile}" 2>/dev/null ||
            true
        )"

        process_guard_pid_is_running "${pid}" || continue

        instance_path="$(
            process_guard_instance_from_pidfile "${pidfile}" ||
            true
        )"

        [[ -n "${instance_path}" ]] || continue

        command="$(
            process_guard_pid_command "${pid}" ||
            true
        )"

        printf '%s\t%s\t%s\n' \
            "${pid}" \
            "${instance_path}" \
            "${command}"

    done < <(process_guard_instance_pidfiles)
}


process_guard_has_active_instances()
{
    local active

    active="$(process_guard_active_instances)"

    [[ -n "${active}" ]]
}


process_guard_assert_no_active_instances()
{
    local active

    active="$(process_guard_active_instances)"

    if [[ -z "${active}" ]]
    then
        return 0
    fi

    echo
    echo "============================================================="
    echo " Atualização bloqueada: servidor de jogo em execução"
    echo " Update blocked: game server is running"
    echo "============================================================="
    echo
    echo "O Capivara não atualizará /opt/dsm enquanto houver"
    echo "uma instância de jogo ativa."
    echo
    echo "Capivara will not update /opt/dsm while a game"
    echo "instance is still running."
    echo

    while IFS=$'\t' read -r pid instance_path command
    do
        [[ -n "${pid}" ]] || continue

        echo "PID      : ${pid}"
        echo "Instância: ${instance_path}"

        if [[ -n "${command}" ]]
        then
            echo "Processo : ${command}"
        fi

        echo

    done <<<"${active}"

    echo "Pare as instâncias de jogo de forma controlada"
    echo "e execute a atualização novamente."
    echo

    return 1
}


# =============================================================
# Legacy dashboard workers
# =============================================================

process_guard_legacy_workers()
{
    local pid
    local args

    while IFS= read -r pid
    do
        [[ "${pid}" =~ ^[0-9]+$ ]] || continue

        process_guard_pid_is_running "${pid}" || continue

        args="$(process_guard_pid_command "${pid}" || true)"

        [[ -n "${args}" ]] || continue

        printf '%s\t%s\n' "${pid}" "${args}"

    done < <(
        pgrep -f \
            "${DSM_ROOT}/dashboard/workers/.*_worker\.sh" \
            2>/dev/null ||
        true
    )
}


process_guard_report_legacy_workers()
{
    local workers

    workers="$(process_guard_legacy_workers)"

    [[ -n "${workers}" ]] || return 0

    echo
    echo "Workers legados detectados:"
    echo "Legacy Dashboard workers detected:"
    echo

    while IFS=$'\t' read -r pid args
    do
        [[ -n "${pid}" ]] || continue

        echo "PID     : ${pid}"
        echo "Processo: ${args}"
        echo

    done <<<"${workers}"
}


# =============================================================
# Pre-update gate
# =============================================================

process_guard_pre_update()
{
    process_guard_report_legacy_workers

    process_guard_assert_no_active_instances
}


export -f process_guard_instances_root
export -f process_guard_instance_pidfiles
export -f process_guard_pid_is_running
export -f process_guard_pid_command
export -f process_guard_instance_from_pidfile
export -f process_guard_active_instances
export -f process_guard_has_active_instances
export -f process_guard_assert_no_active_instances
export -f process_guard_legacy_workers
export -f process_guard_report_legacy_workers
export -f process_guard_pre_update
