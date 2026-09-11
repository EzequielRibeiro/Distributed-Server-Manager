#!/usr/bin/env bash
# Read-only host readiness gate for a downloaded Capivara DSM release.
#
# This script intentionally does not stop services, write under /opt/dsm,
# migrate the database, create backups, replace files, or update systemd.
# It is run from the *target* release so the target version defines the
# compatibility checks that must pass before an operator opens a maintenance
# window.

set -Eeuo pipefail

TARGET_ROOT="${1:-}"
INSTALL_ROOT="${2:-/opt/dsm}"
CONFIG_FILE="${INSTALL_ROOT}/config/dsm.conf"
PRESERVED_TREES=(
    "instances"
    "game-data"
    "runtime/hybrid-agent-state"
    "runtime/hybrid-instance-storage"
)

preflight_fail()
{
    printf 'PRECHECK FAIL: %s\n' "$*" >&2
    return 1
}

preflight_require_root()
{
    if [[ "${EUID}" -ne 0 ]]
    then
        preflight_fail "execute com sudo para que processos, banco e filesystem sejam verificados completamente"
        return 1
    fi
}

preflight_require_commands()
{
    local command_name
    local missing=0

    for command_name in \
        bash curl df du find getent gzip id mountpoint python3 rsync stat systemctl tar
    do
        if ! command -v "${command_name}" >/dev/null 2>&1
        then
            printf 'PRECHECK FAIL: comando obrigatório ausente: %s\n' "${command_name}" >&2
            missing=1
        fi
    done

    [[ "${missing}" -eq 0 ]]
}

preflight_validate_target_package()
{
    local required

    [[ -n "${TARGET_ROOT}" && -d "${TARGET_ROOT}" ]] \
        || { preflight_fail "pacote alvo inexistente: ${TARGET_ROOT:-<vazio>}"; return 1; }

    for required in \
        version \
        bin/cap \
        core/bootstrap.sh \
        core/semver.sh \
        database/manager.py \
        update.sh \
        update-manager/process-guard.sh
    do
        [[ -e "${TARGET_ROOT}/${required}" ]] \
            || { preflight_fail "arquivo obrigatório ausente no pacote alvo: ${required}"; return 1; }
    done
}

preflight_load_configuration()
{
    local account_home=""

    [[ -r "${CONFIG_FILE}" ]] \
        || { preflight_fail "configuração instalada não encontrada ou ilegível: ${CONFIG_FILE}"; return 1; }

    # shellcheck source=/dev/null
    source "${CONFIG_FILE}"

    DSM_DATABASE_DRIVER="${DSM_DATABASE_DRIVER:-sqlite}"
    DSM_DATABASE_NAME="${DSM_DATABASE_NAME:-capivara}"
    DSM_DATABASE_TLS="${DSM_DATABASE_TLS:-preferred}"

    if [[ -z "${DSM_USER:-}" ]]
    then
        DSM_USER="$(stat -c '%U' "${INSTALL_ROOT}" 2>/dev/null || true)"
        [[ "${DSM_USER}" != "root" ]] || DSM_USER=""
    fi

    [[ -n "${DSM_USER:-}" ]] \
        || { preflight_fail "DSM_USER não definido e não pôde ser inferido"; return 1; }

    if [[ -z "${DSM_GROUP:-}" ]]
    then
        DSM_GROUP="$(id -gn "${DSM_USER}" 2>/dev/null || true)"
    fi

    [[ -n "${DSM_GROUP:-}" ]] \
        || { preflight_fail "DSM_GROUP não definido e não pôde ser inferido"; return 1; }

    if [[ -z "${DSM_HOME:-}" ]]
    then
        DSM_HOME="$(getent passwd "${DSM_USER}" 2>/dev/null | cut -d: -f6 || true)"
    fi

    id -u "${DSM_USER}" >/dev/null 2>&1 \
        || { preflight_fail "usuário DSM inexistente: ${DSM_USER}"; return 1; }
    getent group "${DSM_GROUP}" >/dev/null 2>&1 \
        || { preflight_fail "grupo DSM inexistente: ${DSM_GROUP}"; return 1; }
    [[ -n "${DSM_HOME:-}" && -d "${DSM_HOME}" ]] \
        || { preflight_fail "DSM_HOME inexistente ou inválido: ${DSM_HOME:-<vazio>}"; return 1; }

    account_home="$(getent passwd "${DSM_USER}" 2>/dev/null | cut -d: -f6 || true)"
    if [[ -n "${account_home}" && "${account_home}" != "${DSM_HOME}" ]]
    then
        printf 'PRECHECK WARN: DSM_HOME=%s difere do home cadastrado=%s\n' \
            "${DSM_HOME}" "${account_home}" >&2
    fi

    export DSM_DATABASE_DRIVER DSM_DATABASE DSM_DATABASE_HOST DSM_DATABASE_PORT
    export DSM_DATABASE_NAME DSM_DATABASE_USER DSM_DATABASE_PASSWORD_FILE DSM_DATABASE_TLS
}

preflight_validate_versions()
{
    local installed_version
    local target_version
    local comparison
    local semver_lib="${TARGET_ROOT}/core/semver.sh"

    [[ -r "${INSTALL_ROOT}/version" ]] \
        || { preflight_fail "versão instalada não encontrada"; return 1; }

    installed_version="$(tr -d '\r\n' <"${INSTALL_ROOT}/version")"
    target_version="$(tr -d '\r\n' <"${TARGET_ROOT}/version")"

    # shellcheck source=/dev/null
    source "${semver_lib}"

    is_semver "${installed_version}" \
        || { preflight_fail "versão instalada inválida: ${installed_version}"; return 1; }
    is_semver "${target_version}" \
        || { preflight_fail "versão alvo inválida: ${target_version}"; return 1; }

    comparison="$(semver_compare "${target_version}" "${installed_version}")"
    [[ "${comparison}" -eq 1 ]] \
        || { preflight_fail "preflight exige upgrade: instalada=${installed_version} alvo=${target_version}"; return 1; }

    printf 'PRECHECK OK: versão %s -> %s\n' "${installed_version}" "${target_version}"
}

preflight_validate_preserved_data()
{
    local hold="${INSTALL_ROOT}.update-preserved"
    local restore="${INSTALL_ROOT}.update-restore"
    local tree
    local pathname
    local install_device

    [[ ! -L "${INSTALL_ROOT}/runtime" ]] \
        || { preflight_fail "runtime root é symlink; conclua a migração de storage antes do update"; return 1; }

    [[ ! -e "${hold}" && ! -L "${hold}" ]] \
        || { preflight_fail "estado de atualização incompleta existe: ${hold}"; return 1; }
    [[ ! -e "${restore}" && ! -L "${restore}" ]] \
        || { preflight_fail "estado de rollback incompleto existe: ${restore}"; return 1; }

    install_device="$(stat -c %d "$(dirname "${INSTALL_ROOT}")")"
    for tree in "${PRESERVED_TREES[@]}"
    do
        pathname="${INSTALL_ROOT}/${tree}"
        [[ -e "${pathname}" || -L "${pathname}" ]] || continue

        if mountpoint -q "${pathname}"
        then
            preflight_fail "dados protegidos são mountpoint e não podem ser estacionados atomicamente: ${pathname}"
            return 1
        fi

        if [[ "$(stat -c %d "${pathname}")" != "${install_device}" ]]
        then
            preflight_fail "dados protegidos estão em filesystem diferente: ${pathname}"
            return 1
        fi
    done

    printf 'PRECHECK OK: árvores protegidas podem ser preservadas atomicamente\n'
}

preflight_installation_bytes()
{
    local tree
    local -a excludes=()

    for tree in "${PRESERVED_TREES[@]}"
    do
        excludes+=(--exclude="${INSTALL_ROOT}/${tree}")
    done

    du -sb "${excludes[@]}" "${INSTALL_ROOT}" | awk '{print $1}'
}

preflight_validate_disk()
{
    local install_bytes
    local free_bytes
    local required_bytes

    install_bytes="$(preflight_installation_bytes)"
    free_bytes="$(df --output=avail -B1 "${INSTALL_ROOT}" | tail -1 | tr -d ' ')"
    required_bytes=$((install_bytes * 2))

    [[ "${free_bytes}" =~ ^[0-9]+$ && "${required_bytes}" -gt 0 ]] \
        || { preflight_fail "não foi possível calcular espaço em disco"; return 1; }

    if (( free_bytes < required_bytes ))
    then
        preflight_fail "espaço insuficiente: disponível=${free_bytes} necessário=${required_bytes}"
        return 1
    fi

    printf 'PRECHECK OK: espaço em disco disponível=%s necessário=%s\n' \
        "${free_bytes}" "${required_bytes}"
}

preflight_validate_process_and_database_guard()
{
    local guard="${TARGET_ROOT}/update-manager/process-guard.sh"

    DSM_ROOT="${INSTALL_ROOT}"
    INSTALL_DIR="${INSTALL_ROOT}"
    NEW_SRC="${TARGET_ROOT}"
    export DSM_ROOT INSTALL_DIR NEW_SRC

    # shellcheck source=/dev/null
    source "${guard}"
    process_guard_pre_update

    printf 'PRECHECK OK: banco compatível e nenhuma instância de jogo ativa\n'
}

main()
{
    printf 'Capivara DSM update preflight (somente leitura)\n'
    preflight_require_root
    preflight_require_commands
    preflight_validate_target_package
    preflight_load_configuration
    preflight_validate_versions
    preflight_validate_preserved_data
    preflight_validate_disk
    preflight_validate_process_and_database_guard
    printf 'UPDATE PREFLIGHT READY: nenhuma alteração foi aplicada em %s\n' "${INSTALL_ROOT}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    main "$@"
fi
