#!/usr/bin/env bash
# Read-only preflight for the latest approved Capivara DSM release.
#
# Contract:
# - downloads release material only to a temporary directory outside DSM_ROOT;
# - validates the official checksum and archive before extraction;
# - runs the target release's own preflight contract;
# - never stops services, migrates the database, creates a backup, writes the
#   update cache, replaces /opt/dsm, or updates systemd.

set -Eeuo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
export DSM_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UPDATE_MANAGER_ROOT="${DSM_ROOT}/update-manager"
PREFLIGHT_WORKDIR=""

# shellcheck source=/dev/null
source "${DSM_ROOT}/core/bootstrap.sh"

if ! declare -F log_info >/dev/null 2>&1 || ! declare -F log_error >/dev/null 2>&1
then
    [[ ! -f "${DSM_ROOT}/core/logger.sh" ]] || source "${DSM_ROOT}/core/logger.sh"
fi

if ! declare -F is_semver >/dev/null 2>&1 || ! declare -F semver_compare >/dev/null 2>&1
then
    [[ ! -f "${DSM_ROOT}/core/semver.sh" ]] || source "${DSM_ROOT}/core/semver.sh"
fi

declare -F log_info >/dev/null 2>&1 || log_info() { printf '%s\n' "$*"; }
declare -F log_error >/dev/null 2>&1 || log_error() { printf 'Erro: %s\n' "$*" >&2; }

# shellcheck source=/dev/null
source "${UPDATE_MANAGER_ROOT}/config.conf"
# shellcheck source=/dev/null
source "${UPDATE_MANAGER_ROOT}/github-client.sh"
# shellcheck source=/dev/null
source "${UPDATE_MANAGER_ROOT}/verify-release.sh"

preflight_latest_cleanup()
{
    if [[ -n "${PREFLIGHT_WORKDIR:-}" && -d "${PREFLIGHT_WORKDIR}" ]]
    then
        rm -rf -- "${PREFLIGHT_WORKDIR}"
    fi
    PREFLIGHT_WORKDIR=""
}

preflight_latest_fail()
{
    log_error "$*"
    return 1
}

preflight_latest_require_root()
{
    if [[ "${EUID}" -ne 0 ]]
    then
        preflight_latest_fail "Execute com sudo: cap update preflight"
        return 1
    fi
}

preflight_latest_require_commands()
{
    local command_name
    local missing=0

    for command_name in awk curl find grep head jq mktemp tar tr
    do
        if ! command -v "${command_name}" >/dev/null 2>&1
        then
            printf 'PRECHECK FAIL: comando obrigatório ausente: %s\n' "${command_name}" >&2
            missing=1
        fi
    done

    [[ "${missing}" -eq 0 ]]
}

preflight_latest_download()
{
    local url="$1"
    local destination="$2"

    curl \
        --fail \
        --location \
        --silent \
        --show-error \
        --connect-timeout "${DOWNLOAD_TIMEOUT}" \
        --output "${destination}" \
        "${url}"
}

preflight_latest_run()
{
    local current_version
    local release_json
    local latest_version
    local comparison
    local download_url
    local checksum_url
    local package
    local checksum_file
    local checksum
    local extract_root
    local package_root
    local package_version
    local target_preflight

    preflight_latest_require_root
    preflight_latest_require_commands

    current_version="$(tr -d '\r\n' <"${INSTALL_DIR}/version" 2>/dev/null || true)"
    [[ -n "${current_version}" ]] \
        || { preflight_latest_fail "Arquivo de versão instalado não encontrado"; return 1; }
    is_semver "${current_version}" \
        || { preflight_latest_fail "Versão instalada inválida: ${current_version}"; return 1; }

    log_info "Consultando release estável mais recente para preflight"
    release_json="$(github_latest_release)"
    [[ -n "${release_json}" ]] \
        || { preflight_latest_fail "Falha consultando GitHub"; return 1; }
    github_release_channel "${release_json}" \
        || { preflight_latest_fail "Release mais recente não pertence ao canal ${UPDATE_CHANNEL}"; return 1; }

    latest_version="$(github_release_version "${release_json}")"
    latest_version="${latest_version#v}"
    is_semver "${latest_version}" \
        || { preflight_latest_fail "Release sem versão SemVer válida"; return 1; }

    comparison="$(semver_compare "${latest_version}" "${current_version}")"
    case "${comparison}" in
        1)
            ;;
        0)
            printf 'DSM já está atualizado: %s\n' "${current_version}"
            printf 'UPDATE PREFLIGHT NOT NEEDED: nenhuma versão mais nova está disponível.\n'
            return 0
            ;;
        -1)
            preflight_latest_fail "Instalação está à frente da release estável: instalada=${current_version} release=${latest_version}"
            return 1
            ;;
        *)
            preflight_latest_fail "Falha comparando versões"
            return 1
            ;;
    esac

    download_url="$(github_release_download "${release_json}")"
    checksum_url="$(github_release_checksum_download "${release_json}")"
    [[ -n "${download_url}" && -n "${checksum_url}" ]] \
        || { preflight_latest_fail "Release sem pacote/checksum oficial"; return 1; }

    PREFLIGHT_WORKDIR="$(mktemp -d -t capivara-update-preflight.XXXXXX)"
    trap preflight_latest_cleanup EXIT
    package="${PREFLIGHT_WORKDIR}/capivara-dsm-${latest_version}.tar.gz"
    checksum_file="${package}.sha256"
    extract_root="${PREFLIGHT_WORKDIR}/release"
    mkdir -p "${extract_root}"

    printf 'PRECHECK INFO: baixando release %s em diretório temporário\n' "${latest_version}"
    preflight_latest_download "${download_url}" "${package}"
    preflight_latest_download "${checksum_url}" "${checksum_file}"

    checksum="$(awk 'NR == 1 { print $1 }' "${checksum_file}")"
    printf '%s\n' "${checksum}" | grep -Eq '^[[:xdigit:]]{64}$' \
        || { preflight_latest_fail "Checksum SHA256 oficial inválido"; return 1; }

    verify_release "${package}" "${checksum}" \
        || { preflight_latest_fail "Pacote da release falhou na validação criptográfica/estrutural"; return 1; }

    # verify_release validates member paths/links before this extraction.
    tar -xzf "${package}" -C "${extract_root}"
    package_root="$(find "${extract_root}" -mindepth 1 -maxdepth 2 -type f -name version -printf '%h\n' | head -1)"
    [[ -n "${package_root}" ]] \
        || { preflight_latest_fail "Raiz da release não encontrada após validação"; return 1; }

    package_version="$(tr -d '\r\n' <"${package_root}/version")"
    [[ "${package_version}" == "${latest_version}" ]] \
        || { preflight_latest_fail "Versão do pacote diverge da tag: pacote=${package_version} tag=${latest_version}"; return 1; }

    target_preflight="${package_root}/update-manager/preflight.sh"
    [[ -f "${target_preflight}" ]] \
        || { preflight_latest_fail "Release alvo não contém update-manager/preflight.sh"; return 1; }

    printf 'PRECHECK INFO: executando contrato read-only da release alvo %s\n' "${latest_version}"
    bash "${target_preflight}" "${package_root}" "${INSTALL_DIR}"
    printf 'UPDATE PREFLIGHT VERIFIED: release=%s instalada=%s; nenhuma alteração foi aplicada.\n' \
        "${latest_version}" "${current_version}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    preflight_latest_run "$@"
fi
