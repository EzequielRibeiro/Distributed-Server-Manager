#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Installation Provider - Local Package
#
# Instala pacotes já presentes no Agent, sem download externo.
# PACKAGE_ID = caminho absoluto para arquivo ou diretório local.
#
# Variáveis opcionais:
#   DSM_LOCAL_FILENAME=<nome de destino para fonte arquivo>
#   DSM_LOCAL_SHA256=<sha256 esperado para fonte arquivo>
#   DSM_LOCAL_VERSION=<versão lógica>
#   DSM_LOCAL_EXECUTABLE=1|0
#
# Contrato universal:
#   provider_ensure
#   provider_install
#   provider_update
#   provider_verify
#   provider_info
#   provider_version
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
source "${DSM_ROOT}/installer/provider_progress.sh"

LOCAL_PROVIDER_SOURCE=""
LOCAL_PROVIDER_TYPE=""
LOCAL_PROVIDER_FILENAME=""
LOCAL_PROVIDER_SHA256=""
LOCAL_PROVIDER_VERSION=""

local_log()
{
    echo "[DSM][LOCAL] $*"
}

local_error()
{
    echo "[DSM][LOCAL][ERRO] $*" >&2
}

local_provider_ensure()
{
    command -v cp >/dev/null 2>&1 || {
        local_error "cp não disponível."
        return 1
    }

    command -v readlink >/dev/null 2>&1 || {
        local_error "readlink não disponível."
        return 1
    }

    return 0
}

local_provider_resolve_source()
{
    local PACKAGE_ID="${1:-}"
    local SOURCE=""

    if [[ -z "${PACKAGE_ID}" ]]
    then
        local_error "PACKAGE_ID local não informado."
        return 1
    fi

    if [[ "${PACKAGE_ID}" == /* ]]
    then
        SOURCE="${PACKAGE_ID}"
    else
        SOURCE="${DSM_ROOT}/${PACKAGE_ID}"
    fi

    if [[ "${SOURCE}" == "/" ]]
    then
        local_error "A raiz / não pode ser usada como pacote local."
        return 1
    fi

    if [[ ! -e "${SOURCE}" ]]
    then
        local_error "Pacote local não encontrado: ${SOURCE}"
        return 1
    fi

    readlink -f -- "${SOURCE}"
}

local_provider_validate_filename()
{
    local NAME="${1:-}"

    [[ -n "${NAME}" ]] || return 1
    [[ "${NAME}" != "." && "${NAME}" != ".." ]] || return 1
    [[ "${NAME}" != */* ]] || return 1
    return 0
}

local_provider_sha256()
{
    local FILE="$1"
    command -v sha256sum >/dev/null 2>&1 || return 1
    sha256sum -- "${FILE}" | awk '{print $1}'
}

local_provider_write_metadata()
{
    local INSTALL_PATH="$1"
    local SOURCE="$2"
    local TYPE="$3"
    local FILENAME="${4:-}"
    local SHA256="${5:-}"
    local VERSION="${6:-current}"

    mkdir -p "${INSTALL_PATH}/.dsm"

    {
        printf 'PROVIDER=%q\n' "local"
        printf 'SOURCE=%q\n' "${SOURCE}"
        printf 'TYPE=%q\n' "${TYPE}"
        printf 'FILENAME=%q\n' "${FILENAME}"
        printf 'SHA256=%q\n' "${SHA256}"
        printf 'VERSION=%q\n' "${VERSION}"
    } > "${INSTALL_PATH}/.dsm/local-provider.conf"
}

local_provider_read_metadata()
{
    local FILE="$1/.dsm/local-provider.conf"
    [[ -f "${FILE}" ]] || return 1

    SOURCE=""
    TYPE=""
    FILENAME=""
    SHA256=""
    VERSION=""

    # Arquivo produzido exclusivamente pelo próprio Capivara.
    # shellcheck source=/dev/null
    source "${FILE}"

    LOCAL_PROVIDER_SOURCE="${SOURCE:-}"
    LOCAL_PROVIDER_TYPE="${TYPE:-}"
    LOCAL_PROVIDER_FILENAME="${FILENAME:-}"
    LOCAL_PROVIDER_SHA256="${SHA256:-}"
    LOCAL_PROVIDER_VERSION="${VERSION:-current}"
}

local_provider_apply_executable()
{
    local INSTALL_PATH="$1"
    local EXPECTED_EXECUTABLE="${2:-}"

    [[ -n "${EXPECTED_EXECUTABLE}" ]] || return 0

    if [[ "${EXPECTED_EXECUTABLE}" == /* || "${EXPECTED_EXECUTABLE}" == *".."* ]]
    then
        local_error "Executável esperado contém caminho inválido."
        return 1
    fi

    local TARGET="${INSTALL_PATH}/${EXPECTED_EXECUTABLE}"

    if [[ "${DSM_LOCAL_EXECUTABLE:-0}" == "1" || -f "${TARGET}" ]]
    then
        if [[ ! -f "${TARGET}" ]]
        then
            local_error "Executável esperado não encontrado: ${TARGET}"
            return 1
        fi

        provider_progress_publish "installing" 72 "Aplicando permissão de execução ao pacote local"
        chmod +x -- "${TARGET}" || return 1
        [[ -x "${TARGET}" ]] || return 1
    fi
}

local_provider_install()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local AUTH="${3:-}"
    local EXPECTED_EXECUTABLE="${4:-${DSM_EXPECTED_EXECUTABLE:-}}"

    local SOURCE TYPE FILENAME DESTINATION EXPECTED_SHA256 ACTUAL_SHA256 VERSION

    local_provider_ensure || return 1

    SOURCE="$(local_provider_resolve_source "${PACKAGE_ID}")" || return 1

    if [[ -z "${INSTALL_PATH}" || "${INSTALL_PATH}" == "/" ]]
    then
        local_error "Diretório de instalação inválido."
        return 1
    fi

    local INSTALL_REAL
    INSTALL_REAL="$(readlink -m -- "${INSTALL_PATH}")"

    if [[ "${SOURCE}" == "${INSTALL_REAL}" || "${SOURCE}" == "${INSTALL_REAL}/"* ]]
    then
        local_error "A origem local não pode estar dentro do staging de destino."
        return 1
    fi

    EXPECTED_SHA256="${DSM_LOCAL_SHA256:-}"
    VERSION="${DSM_LOCAL_VERSION:-current}"

    mkdir -p "${INSTALL_PATH}"

    provider_progress_publish "copying" 25 "Preparando pacote local"

    if [[ -f "${SOURCE}" ]]
    then
        TYPE="file"
        FILENAME="${DSM_LOCAL_FILENAME:-$(basename -- "${SOURCE}")}"

        if ! local_provider_validate_filename "${FILENAME}"
        then
            local_error "Nome de arquivo local inválido: ${FILENAME}"
            return 1
        fi

        DESTINATION="${INSTALL_PATH}/${FILENAME}"

        local_log "Origem  : ${SOURCE}"
        local_log "Destino : ${DESTINATION}"

        provider_progress_publish "copying" 45 "Copiando pacote local"
        cp -a -- "${SOURCE}" "${DESTINATION}" || return 1

        if [[ -n "${EXPECTED_SHA256}" ]]
        then
            provider_progress_publish "validating" 65 "Validando SHA256 do pacote local"
            ACTUAL_SHA256="$(local_provider_sha256 "${DESTINATION}")" || return 1

            if [[ "${ACTUAL_SHA256,,}" != "${EXPECTED_SHA256,,}" ]]
            then
                local_error "SHA256 inválido. Esperado=${EXPECTED_SHA256} Obtido=${ACTUAL_SHA256}"
                rm -f -- "${DESTINATION}"
                return 1
            fi
        else
            ACTUAL_SHA256="$(local_provider_sha256 "${DESTINATION}" 2>/dev/null || true)"
        fi

    elif [[ -d "${SOURCE}" ]]
    then
        TYPE="directory"
        FILENAME=""

        if [[ -n "${EXPECTED_SHA256}" ]]
        then
            local_error "DSM_LOCAL_SHA256 só é suportado para fonte arquivo."
            return 1
        fi

        local_log "Origem  : ${SOURCE}/"
        local_log "Destino : ${INSTALL_PATH}/"

        provider_progress_publish "copying" 45 "Copiando diretório local"
        cp -a -- "${SOURCE}/." "${INSTALL_PATH}/" || return 1
        ACTUAL_SHA256=""
    else
        local_error "Tipo de pacote local não suportado."
        return 1
    fi

    local_provider_apply_executable "${INSTALL_PATH}" "${EXPECTED_EXECUTABLE}" || return 1

    provider_progress_publish "metadata" 74 "Gravando metadata do pacote local"
    local_provider_write_metadata \
        "${INSTALL_PATH}" \
        "${SOURCE}" \
        "${TYPE}" \
        "${FILENAME}" \
        "${ACTUAL_SHA256}" \
        "${VERSION}" || return 1

    provider_progress_publish "copied" 75 "Pacote local preparado"
    local_log "Pacote local instalado no staging."
    return 0
}

local_provider_update()
{
    local_provider_install "$@"
}

local_provider_verify()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local EXECUTABLE="${3:-}"

    local_provider_read_metadata "${INSTALL_PATH}" || {
        local_error "Metadata local não encontrada."
        return 1
    }

    case "${LOCAL_PROVIDER_TYPE}" in
        file)
            local FILE="${INSTALL_PATH}/${LOCAL_PROVIDER_FILENAME}"
            [[ -f "${FILE}" ]] || return 1

            if [[ -n "${LOCAL_PROVIDER_SHA256}" ]]
            then
                local ACTUAL
                ACTUAL="$(local_provider_sha256 "${FILE}")" || return 1
                [[ "${ACTUAL,,}" == "${LOCAL_PROVIDER_SHA256,,}" ]] || return 1
            fi
        ;;

        directory)
            [[ -d "${INSTALL_PATH}" ]] || return 1
        ;;

        *)
            local_error "Metadata local contém TYPE inválido."
            return 1
        ;;
    esac

    if [[ -n "${EXECUTABLE}" ]]
    then
        [[ -x "${INSTALL_PATH}/${EXECUTABLE}" ]] || return 1
    fi

    return 0
}

local_provider_info()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    if ! local_provider_read_metadata "${INSTALL_PATH}"
    then
        echo "provider=local"
        echo "source=${PACKAGE_ID}"
        echo "version=unknown"
        return 1
    fi

    echo "provider=local"
    echo "source=${LOCAL_PROVIDER_SOURCE}"
    echo "type=${LOCAL_PROVIDER_TYPE}"
    echo "file=${LOCAL_PROVIDER_FILENAME}"
    echo "version=${LOCAL_PROVIDER_VERSION:-current}"
}

local_provider_version()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    if local_provider_read_metadata "${INSTALL_PATH}"
    then
        echo "${LOCAL_PROVIDER_VERSION:-current}"
    else
        echo "unknown"
        return 1
    fi
}

provider_ensure()  { local_provider_ensure; }
provider_install() { local_provider_install "$@"; }
provider_update()  { local_provider_update "$@"; }
provider_verify()  { local_provider_verify "$@"; }
provider_info()    { local_provider_info "$@"; }
provider_version() { local_provider_version "$@"; }

export -f local_log local_error
export -f local_provider_ensure local_provider_resolve_source local_provider_validate_filename
export -f local_provider_sha256 local_provider_write_metadata local_provider_read_metadata
export -f local_provider_apply_executable local_provider_install local_provider_update
export -f local_provider_verify local_provider_info local_provider_version
export -f provider_ensure provider_install provider_update provider_verify provider_info provider_version
