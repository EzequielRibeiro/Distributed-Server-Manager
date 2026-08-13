#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
# Installation Provider - HTTP Archive
#
# Downloads an archive from HTTP/HTTPS into staging, validates it,
# extracts it safely and exposes the universal provider contract.
# Supported archive types: zip, tar, tar.gz/tgz, tar.xz/txz.
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

http_archive_log(){ echo "[DSM][HTTP-ARCHIVE] $*"; }
http_archive_error(){ echo "[DSM][HTTP-ARCHIVE][ERRO] $*" >&2; }

http_archive_detect_type()
{
    local FILE="${1:-}"
    local EXPLICIT="${DSM_HTTP_ARCHIVE_TYPE:-auto}"

    if [[ "${EXPLICIT}" != "" && "${EXPLICIT}" != "auto" ]]
    then
        echo "${EXPLICIT}"
        return 0
    fi

    case "${FILE,,}" in
        *.zip) echo zip ;;
        *.tar.gz|*.tgz) echo tar.gz ;;
        *.tar.xz|*.txz) echo tar.xz ;;
        *.tar) echo tar ;;
        *) return 1 ;;
    esac
}

http_archive_ensure()
{
    command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || {
        http_archive_error "curl ou wget é obrigatório."
        return 1
    }

    command -v sha256sum >/dev/null 2>&1 || {
        http_archive_error "sha256sum é obrigatório."
        return 1
    }

    return 0
}

http_archive_download()
{
    local URL="$1" DEST="$2"
    local USER_AGENT="${DSM_HTTP_ARCHIVE_USER_AGENT:-Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36}"
    local REFERER="${DSM_HTTP_REFERER:-}"

    mkdir -p "$(dirname "${DEST}")"

    if command -v curl >/dev/null 2>&1
    then
        local CURL_ARGS=(
            --fail
            --location
            --retry 3
            --connect-timeout 30
            --max-time 1800
            --user-agent "${USER_AGENT}"
            --output "${DEST}"
        )

        if [[ -n "${REFERER}" ]]
        then
            CURL_ARGS+=(--referer "${REFERER}")
        fi

        curl "${CURL_ARGS[@]}" "${URL}"
    else
        local WGET_ARGS=(
            --tries=3
            --timeout=30
            --user-agent="${USER_AGENT}"
            --output-document="${DEST}"
        )

        if [[ -n "${REFERER}" ]]
        then
            WGET_ARGS+=(--referer="${REFERER}")
        fi

        wget "${WGET_ARGS[@]}" "${URL}"
    fi

    [[ -s "${DEST}" ]] || {
        http_archive_error "Download resultou em arquivo vazio."
        rm -f "${DEST}"
        return 1
    }
}

http_archive_sha256()
{
    sha256sum "$1" | awk '{print $1}'
}

http_archive_verify_checksum()
{
    local FILE="$1" EXPECTED="${2:-}" ACTUAL
    [[ -z "${EXPECTED}" ]] && return 0

    ACTUAL="$(http_archive_sha256 "${FILE}")" || return 1
    if [[ "${ACTUAL,,}" != "${EXPECTED,,}" ]]
    then
        http_archive_error "SHA256 inválido. Esperado=${EXPECTED} Obtido=${ACTUAL}"
        return 1
    fi

    echo "[OK] SHA256: ${ACTUAL}"
}

http_archive_validate_entries()
{
    local ARCHIVE="$1" TYPE="$2" LIST

    case "${TYPE}" in
        zip)
            command -v unzip >/dev/null 2>&1 || {
                http_archive_error "unzip é obrigatório para arquivos ZIP."
                return 1
            }
            LIST="$(unzip -Z1 "${ARCHIVE}")" || return 1
            ;;
        tar|tar.gz|tar.xz)
            command -v tar >/dev/null 2>&1 || {
                http_archive_error "tar é obrigatório."
                return 1
            }
            LIST="$(tar -tf "${ARCHIVE}")" || return 1
            ;;
        *)
            http_archive_error "Tipo de archive não suportado: ${TYPE}"
            return 1
            ;;
    esac

    while IFS= read -r ENTRY
    do
        [[ -z "${ENTRY}" ]] && continue
        if [[ "${ENTRY}" == /* || "${ENTRY}" == ../* || "${ENTRY}" == */../* || "${ENTRY}" == *"/.." ]]
        then
            http_archive_error "Entrada insegura no archive: ${ENTRY}"
            return 1
        fi
    done <<< "${LIST}"
}

http_archive_extract()
{
    local ARCHIVE="$1" TYPE="$2" DEST="$3"
    http_archive_validate_entries "${ARCHIVE}" "${TYPE}" || return 1

    case "${TYPE}" in
        zip) unzip -q "${ARCHIVE}" -d "${DEST}" ;;
        tar) tar -xf "${ARCHIVE}" -C "${DEST}" ;;
        tar.gz) tar -xzf "${ARCHIVE}" -C "${DEST}" ;;
        tar.xz) tar -xJf "${ARCHIVE}" -C "${DEST}" ;;
        *) return 1 ;;
    esac
}

http_archive_write_metadata()
{
    local INSTALL_PATH="$1" URL="$2" FILENAME="$3" SHA256="$4"
    local VERSION="$5" TYPE="$6" EXECUTABLE="$7"
    local META_DIR="${INSTALL_PATH}/.dsm"

    mkdir -p "${META_DIR}"
    {
        printf 'PROVIDER=%q\n' "http-archive"
        printf 'URL=%q\n' "${URL}"
        printf 'FILENAME=%q\n' "${FILENAME}"
        printf 'SHA256=%q\n' "${SHA256}"
        printf 'VERSION=%q\n' "${VERSION}"
        printf 'ARCHIVE_TYPE=%q\n' "${TYPE}"
        printf 'EXECUTABLE=%q\n' "${EXECUTABLE}"
    } > "${META_DIR}/http-archive-provider.conf"
}

http_archive_read_metadata()
{
    local INSTALL_PATH="$1"
    local META="${INSTALL_PATH}/.dsm/http-archive-provider.conf"
    [[ -f "${META}" ]] || return 1
    # shellcheck source=/dev/null
    source "${META}"
}

http_archive_install()
{
    local URL="${1:-}" INSTALL_PATH="${2:-}" AUTH="${3:-}" EXPECTED_EXECUTABLE="${4:-${DSM_EXPECTED_EXECUTABLE:-}}"
    local FILENAME TYPE DOWNLOAD_DIR ARCHIVE EXPECTED_SHA VERSION

    [[ "${URL}" == http://* || "${URL}" == https://* ]] || {
        http_archive_error "URL HTTP/HTTPS inválida: ${URL}"
        return 1
    }
    [[ -n "${INSTALL_PATH}" ]] || return 1
    http_archive_ensure || return 1

    FILENAME="${DSM_HTTP_FILENAME:-${URL%%\?*}}"
    FILENAME="$(basename "${FILENAME}")"
    [[ -n "${FILENAME}" && "${FILENAME}" != "." && "${FILENAME}" != ".." && "${FILENAME}" != */* ]] || {
        http_archive_error "Nome de arquivo inválido: ${FILENAME}"
        return 1
    }

    TYPE="$(http_archive_detect_type "${FILENAME}")" || {
        http_archive_error "Não foi possível detectar o formato de ${FILENAME}."
        return 1
    }
    EXPECTED_SHA="${DSM_HTTP_SHA256:-}"
    VERSION="${DSM_HTTP_VERSION:-current}"

    mkdir -p "${INSTALL_PATH}"
    DOWNLOAD_DIR="${INSTALL_PATH}/.dsm/downloads"
    ARCHIVE="${DOWNLOAD_DIR}/${FILENAME}"

    echo
    echo "============================================"
    echo " Capivara - HTTP Archive Provider"
    echo "============================================"
    echo
    echo "URL      : ${URL}"
    echo "Archive  : ${FILENAME} (${TYPE})"
    echo "Destino  : ${INSTALL_PATH}"
    echo "Versão   : ${VERSION}"
    echo

    http_archive_download "${URL}" "${ARCHIVE}" || return 1
    http_archive_verify_checksum "${ARCHIVE}" "${EXPECTED_SHA}" || return 1

    http_archive_log "Validando e extraindo archive..."
    http_archive_extract "${ARCHIVE}" "${TYPE}" "${INSTALL_PATH}" || return 1

    if [[ -n "${EXPECTED_EXECUTABLE}" ]]
    then
        if [[ ! -f "${INSTALL_PATH}/${EXPECTED_EXECUTABLE}" ]]
        then
            http_archive_error "Executável esperado não encontrado após extração: ${EXPECTED_EXECUTABLE}"
            return 1
        fi

        if [[ "${DSM_HTTP_ARCHIVE_EXECUTABLE:-1}" == "1" ]]
        then
            chmod +x "${INSTALL_PATH}/${EXPECTED_EXECUTABLE}" || return 1
        fi
    fi

    http_archive_write_metadata \
        "${INSTALL_PATH}" "${URL}" "${FILENAME}" "${EXPECTED_SHA}" \
        "${VERSION}" "${TYPE}" "${EXPECTED_EXECUTABLE}" || return 1

    http_archive_log "Pacote extraído no staging."
}

http_archive_update(){ http_archive_install "$@"; }

http_archive_verify()
{
    local PACKAGE_ID="${1:-}" INSTALL_PATH="${2:-}" EXPECTED_EXECUTABLE="${3:-}"
    http_archive_read_metadata "${INSTALL_PATH}" || {
        http_archive_error "Metadata HTTP Archive ausente."
        return 1
    }

    local TARGET="${EXPECTED_EXECUTABLE:-${EXECUTABLE:-}}"
    [[ -n "${TARGET}" ]] || {
        http_archive_error "Executável esperado não informado."
        return 1
    }

    [[ -f "${INSTALL_PATH}/${TARGET}" ]] || {
        http_archive_error "Arquivo extraído ausente: ${INSTALL_PATH}/${TARGET}"
        return 1
    }

    echo "[OK] HTTP archive: ${FILENAME:-unknown}"
    echo "[OK] Arquivo extraído: ${TARGET}"
}

http_archive_info()
{
    local PACKAGE_ID="${1:-}" INSTALL_PATH="${2:-}"
    if http_archive_read_metadata "${INSTALL_PATH}"
    then
        echo "provider=http-archive"
        echo "url=${URL:-${PACKAGE_ID}}"
        echo "file=${FILENAME:-unknown}"
        echo "archive_type=${ARCHIVE_TYPE:-unknown}"
        echo "version=${VERSION:-current}"
    else
        echo "provider=http-archive"
        echo "url=${PACKAGE_ID}"
        echo "version=unknown"
        return 1
    fi
}

http_archive_version()
{
    local PACKAGE_ID="${1:-}" INSTALL_PATH="${2:-}"
    http_archive_read_metadata "${INSTALL_PATH}" || { echo unknown; return 1; }
    echo "${VERSION:-current}"
}

provider_ensure(){ http_archive_ensure; }
provider_install(){ http_archive_install "$@"; }
provider_update(){ http_archive_update "$@"; }
provider_verify(){ http_archive_verify "$@"; }
provider_info(){ http_archive_info "$@"; }
provider_version(){ http_archive_version "$@"; }

export -f http_archive_log http_archive_error http_archive_detect_type http_archive_ensure
export -f http_archive_download http_archive_sha256 http_archive_verify_checksum
export -f http_archive_validate_entries http_archive_extract
export -f http_archive_write_metadata http_archive_read_metadata
export -f http_archive_install http_archive_update http_archive_verify
export -f http_archive_info http_archive_version
export -f provider_ensure provider_install provider_update provider_verify provider_info provider_version
