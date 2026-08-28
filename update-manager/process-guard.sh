#!/usr/bin/env bash

# =============================================================
# Capivara DSM - Update Process Guard
#
# Responsabilidades:
# - validar a compatibilidade do banco com o pacote alvo;
# - detectar instâncias de jogos ainda em execução;
# - impedir atualização da árvore /opt/dsm enquanto houver
#   runtime de jogo ativo;
# - detectar workers legados do Dashboard executados fora
#   do controle atual do systemd.
#
# Este módulo NÃO encerra servidores de jogos nem altera o banco.
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
PROCESS_GUARD_CGROUP_ROOT="${PROCESS_GUARD_CGROUP_ROOT:-/sys/fs/cgroup}"


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
# Target database compatibility
# =============================================================

process_guard_database_check_is_upgradeable()
{
    local payload="${1:-}"
    local target_root="${2:-}"

    [[ -n "${payload}" && -n "${target_root}" ]] || return 1

    CAPIVARA_DATABASE_CHECK_PAYLOAD="${payload}" \
        python3 - "${target_root}" <<'PY'
import json
import os
import sys
from pathlib import Path

try:
    payload = json.loads(os.environ["CAPIVARA_DATABASE_CHECK_PAYLOAD"])
except (KeyError, json.JSONDecodeError):
    raise SystemExit(1)

if payload.get("kind") != "DatabaseCheck":
    raise SystemExit(1)
if payload.get("connected") is not True or payload.get("initialized") is not True:
    raise SystemExit(1)
if not payload.get("baseline") or payload.get("baseline") != payload.get("expected_baseline"):
    raise SystemExit(1)
if payload.get("missing_tables"):
    raise SystemExit(1)
if payload.get("upgrade_error") is not None:
    raise SystemExit(1)

database_dir = Path(sys.argv[1]) / "database"
if not database_dir.is_dir():
    raise SystemExit(1)
sys.path.insert(0, str(database_dir))

try:
    from baseline_upgrade_engine import (
        LEGACY_BASELINE_START_VERSION,
        UPGRADES,
        latest_upgrade_version,
    )
except Exception:
    raise SystemExit(1)

pending = payload.get("pending_upgrades")
if not isinstance(pending, list):
    raise SystemExit(1)

registered = {(upgrade.version, upgrade.name) for upgrade in UPGRADES}
for item in pending:
    if not isinstance(item, dict):
        raise SystemExit(1)
    pair = (item.get("version"), item.get("name"))
    if pair not in registered:
        raise SystemExit(1)

if payload.get("upgrade_latest") != latest_upgrade_version():
    raise SystemExit(1)

checksum_matches = payload.get("checksum_matches") is True
ledger_present = payload.get("upgrade_ledger") is True
installed_checksum = payload.get("baseline_checksum")

# Exact current consolidated baseline without a ledger is safe: the target
# reconciler only seeds the ledger because the schema already includes all
# registered extensions.
if checksum_matches:
    raise SystemExit(0 if (not ledger_present or pending) else 1)

# Once a valid ledger exists, a checksum change is advanced only through the
# target release's registered additive upgrades.
if ledger_present:
    raise SystemExit(0 if pending else 1)

# Pre-ledger checksum changes are accepted only through the finite compatibility
# bridge declared by the target release itself.
if installed_checksum in LEGACY_BASELINE_START_VERSION and pending:
    raise SystemExit(0)

raise SystemExit(1)
PY
}


process_guard_assert_target_database_compatible()
{
    local target_root="${NEW_SRC:-}"
    local install_root="${INSTALL_DIR:-${DSM_ROOT}}"
    local manager
    local check_output=""
    local check_status=0

    if [[ -z "${target_root}" ]]
    then
        echo "ERRO: pacote alvo não definido para o preflight do banco." >&2
        echo "ERROR: target package is not defined for database preflight." >&2
        return 1
    fi

    manager="${target_root}/database/manager.py"

    if [[ ! -f "${manager}" ]]
    then
        echo "ERRO: gerenciador de banco do pacote alvo ausente: ${manager}" >&2
        echo "ERROR: target package database manager is missing: ${manager}" >&2
        return 1
    fi

    echo
    echo "Validando compatibilidade do banco com o pacote alvo..."
    echo "Validating database compatibility with target package..."

    if check_output="$(python3 "${manager}" --root "${install_root}" check)"
    then
        [[ -n "${check_output}" ]] && printf '%s\n' "${check_output}"
        echo "[OK] Banco compatível com o pacote alvo | Database compatible with target package."
        return 0
    else
        check_status=$?
    fi

    [[ -n "${check_output}" ]] && printf '%s\n' "${check_output}"

    if (( check_status == 1 )) \
        && process_guard_database_check_is_upgradeable "${check_output}" "${target_root}"
    then
        echo
        echo "[OK] Banco compatível com reconciliação Baseline v2 pendente."
        echo "[OK] Database compatible with pending Baseline v2 reconciliation."
        echo "Os upgrades aditivos registrados serão aplicados após a parada controlada dos serviços."
        echo "Registered additive upgrades will be applied after services are stopped safely."
        return 0
    fi

    echo
    echo "============================================================="
    echo " Atualização bloqueada: banco incompatível com a versão alvo"
    echo " Update blocked: database is incompatible with target version"
    echo "============================================================="
    echo
    echo "Nenhum serviço foi parado e nenhum arquivo da instalação foi aplicado."
    echo "No service was stopped and no installation file was applied."
    echo
    echo "O Capivara não executa migração histórica entre baselines incompatíveis."
    echo "Capivara does not perform historical migration between incompatible baselines."
    echo
    return 1
}

# =============================================================
# systemd / cgroup runtime authority
# =============================================================

process_guard_systemd_cgroups()
{
    local cgroup_root

    cgroup_root="${PROCESS_GUARD_CGROUP_ROOT}"

    [[ -d "${cgroup_root}" ]] || return 0

    find "${cgroup_root}" \
        -type d \
        -name 'capivara-instance-*.service' \
        -print \
        2>/dev/null
}


process_guard_unit_from_cgroup()
{
    local cgroup="${1:-}"

    [[ -n "${cgroup}" ]] || return 1

    basename "${cgroup}"
}


process_guard_active_systemd_instances()
{
    local cgroup
    local procs_file
    local unit
    local pid
    local command

    while IFS= read -r cgroup
    do
        [[ -d "${cgroup}" ]] || continue

        procs_file="${cgroup}/cgroup.procs"

        [[ -r "${procs_file}" ]] || continue

        unit="$(
            process_guard_unit_from_cgroup "${cgroup}" ||
            true
        )"

        [[ -n "${unit}" ]] || continue

        while IFS= read -r pid
        do
            [[ "${pid}" =~ ^[0-9]+$ ]] || continue

            process_guard_pid_is_running "${pid}" ||
                continue

            command="$(
                process_guard_pid_command "${pid}" ||
                true
            )"

            printf '%s\t%s\t%s\n' \
                "${pid}" \
                "systemd:${unit}" \
                "${command}"

        done <"${procs_file}"

    done < <(process_guard_systemd_cgroups)
}


# =============================================================
# Legacy PID-file runtime
# =============================================================

process_guard_active_pidfile_instances()
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

        process_guard_pid_is_running "${pid}" ||
            continue

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


# =============================================================
# Defensive process discovery
# =============================================================

process_guard_active_process_instances()
{
    local snapshot
    local line
    local pid
    local command
    local instance_path
    local remainder

    snapshot="$(
        ps -eo pid=,args= 2>/dev/null ||
        true
    )"

    [[ -n "${snapshot}" ]] || return 0

    while IFS= read -r line
    do
        pid="$(
            printf '%s\n' "${line}" |
                awk '{print $1}'
        )"

        [[ "${pid}" =~ ^[0-9]+$ ]] || continue

        command="$(
            printf '%s\n' "${line}" |
                sed -E 's/^[[:space:]]*[0-9]+[[:space:]]+//'
        )"

        case "${command}" in
            "${DSM_ROOT}"/instances/*)
                ;;
            *)
                continue
                ;;
        esac

        remainder="${command#"${DSM_ROOT}/instances/"}"

        instance_path="${DSM_ROOT}/instances/${remainder}"

        #
        # A referência de instância é somente informativa aqui.
        # Mesmo que o diretório original já tenha sido removido,
        # o processo continua sendo motivo suficiente para
        # bloquear a atualização.
        #
        instance_path="$(
            printf '%s\n' "${instance_path}" |
                awk '{print $1}'
        )"

        printf '%s\t%s\t%s\n' \
            "${pid}" \
            "${instance_path}" \
            "${command}"

    done <<<"${snapshot}"
}

# =============================================================
# Active game instances
# =============================================================

process_guard_active_instances()
{
    {
        #
        # 1. Autoridade primária:
        #    transient units/cgroups do Capivara.
        #
        process_guard_active_systemd_instances

        #
        # 2. Compatibilidade:
        #    runtimes antigos baseados em process.pid.
        #
        process_guard_active_pidfile_instances

        #
        # 3. Defesa adicional:
        #    processo vivo executando diretamente sob
        #    ${DSM_ROOT}/instances.
        #
        process_guard_active_process_instances

    } |
        awk -F '\t' '
            NF >= 2 && !seen[$1]++ {
                print
            }
        '
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
    process_guard_assert_target_database_compatible

    process_guard_report_legacy_workers

    process_guard_assert_no_active_instances
}


export -f process_guard_instances_root
export -f process_guard_instance_pidfiles
export -f process_guard_pid_is_running
export -f process_guard_pid_command
export -f process_guard_instance_from_pidfile
export -f process_guard_database_check_is_upgradeable
export -f process_guard_assert_target_database_compatible
export -f process_guard_active_instances
export -f process_guard_has_active_instances
export -f process_guard_assert_no_active_instances
export -f process_guard_legacy_workers
export -f process_guard_report_legacy_workers
export -f process_guard_pre_update
export -f process_guard_systemd_cgroups
export -f process_guard_unit_from_cgroup
export -f process_guard_active_systemd_instances
export -f process_guard_active_pidfile_instances
export -f process_guard_active_process_instances
