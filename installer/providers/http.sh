#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Installation Provider - HTTP
#
# Responsável por:
#
# - download de arquivos via HTTP/HTTPS
# - suporte a curl ou wget
# - validação opcional por SHA256
# - instalação em diretório de staging
# - exposição da API universal de providers
#
# Este provider NÃO conhece jogos específicos.
#
# Contrato:
#
# provider_ensure()
# provider_install()
# provider_update()
# provider_verify()
# provider_info()
# provider_version()
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# =============================================================
# Estado do provider
# =============================================================

HTTP_PROVIDER_TOOL=""
HTTP_PROVIDER_URL=""
HTTP_PROVIDER_FILENAME=""
HTTP_PROVIDER_SHA256=""
HTTP_PROVIDER_VERSION=""

# =============================================================
# Logger
# =============================================================

http_log()
{
    echo "[DSM][HTTP] $*"
}

http_error()
{
    echo "[DSM][HTTP][ERRO] $*" >&2
}

# =============================================================
# Detectar ferramenta de download
#
# Preferência:
#
# 1. curl
# 2. wget
#
# =============================================================

http_provider_detect_tool()
{
    if command -v curl >/dev/null 2>&1
    then
        HTTP_PROVIDER_TOOL="curl"
        return 0
    fi

    if command -v wget >/dev/null 2>&1
    then
        HTTP_PROVIDER_TOOL="wget"
        return 0
    fi

    HTTP_PROVIDER_TOOL=""

    return 1
}

# =============================================================
# Ensure
# =============================================================

http_provider_ensure()
{
    if ! http_provider_detect_tool
    then
        http_error "Nenhum cliente HTTP disponível."
        http_error "Instale curl ou wget."

        return 1
    fi

    http_log "Cliente HTTP disponível: ${HTTP_PROVIDER_TOOL}"

    return 0
}

# =============================================================
# Validar URL
#
# Nesta primeira versão aceitamos apenas:
#
# http://
# https://
#
# =============================================================

http_provider_validate_url()
{
    local URL="${1:-}"

    if [[ -z "${URL}" ]]
    then
        http_error "URL não informada."
        return 1
    fi

    case "${URL}" in

        http://*|https://*)
            return 0
            ;;

        *)
            http_error "URL inválida:"
            http_error "${URL}"

            return 1
            ;;

    esac
}

# =============================================================
# Determinar nome do arquivo
# =============================================================

http_provider_filename()
{
    local URL="$1"
    local FILENAME

    # Remove query string antes de obter basename.
    FILENAME="${URL%%\?*}"
    FILENAME="$(basename "${FILENAME}")"

    if [[ -z "${FILENAME}" || "${FILENAME}" == "/" || "${FILENAME}" == "." ]]
    then
        FILENAME="download.bin"
    fi

    echo "${FILENAME}"
}

# =============================================================
# Download
# =============================================================

http_provider_download()
{
    local URL="$1"
    local DESTINATION="$2"

    http_provider_ensure || return 1
    http_provider_validate_url "${URL}" || return 1

    mkdir -p "$(dirname "${DESTINATION}")"

    http_log "Baixando:"
    http_log "${URL}"

    http_log "Destino:"
    http_log "${DESTINATION}"

    case "${HTTP_PROVIDER_TOOL}" in

        curl)

            if ! curl \
                --fail \
                --location \
                --retry 3 \
                --connect-timeout 30 \
                --output "${DESTINATION}" \
                "${URL}"
            then
                http_error "Falha no download via curl."

                rm -f "${DESTINATION}"

                return 1
            fi
            ;;

        wget)

            if ! wget \
                --tries=3 \
                --timeout=30 \
                --output-document="${DESTINATION}" \
                "${URL}"
            then
                http_error "Falha no download via wget."

                rm -f "${DESTINATION}"

                return 1
            fi
            ;;

        *)

            http_error "Cliente HTTP desconhecido."
            return 1
            ;;

    esac

    if [[ ! -s "${DESTINATION}" ]]
    then
        http_error "Download resultou em arquivo vazio."

        rm -f "${DESTINATION}"

        return 1
    fi

    http_log "Download concluído."

    return 0
}


# =============================================================
# SHA256
# =============================================================

http_provider_sha256()
{
    local FILE="$1"

    if ! command -v sha256sum >/dev/null 2>&1
    then
        http_error "sha256sum não disponível."
        return 1
    fi

    if [[ ! -f "${FILE}" ]]
    then
        http_error "Arquivo não encontrado:"
        http_error "${FILE}"

        return 1
    fi

    sha256sum "${FILE}" | awk '{print $1}'
}

# =============================================================
# Validar checksum
#
# Se EXPECTED_SHA256 estiver vazio, checksum é opcional.
#
# =============================================================

http_provider_verify_checksum()
{
    local FILE="$1"
    local EXPECTED_SHA256="${2:-}"

    local ACTUAL_SHA256

    if [[ -z "${EXPECTED_SHA256}" ]]
    then
        http_log "SHA256 não informado; verificação ignorada."
        return 0
    fi

    ACTUAL_SHA256="$(
        http_provider_sha256 "${FILE}"
    )" || return 1

    if [[ "${ACTUAL_SHA256,,}" != "${EXPECTED_SHA256,,}" ]]
    then
        http_error "SHA256 inválido."
        http_error "Esperado : ${EXPECTED_SHA256}"
        http_error "Obtido   : ${ACTUAL_SHA256}"

        return 1
    fi

    echo "[OK] SHA256: ${ACTUAL_SHA256}"

    return 0
}

# =============================================================
# Metadata
#
# O provider grava metadata dentro da instalação.
#
# Isso permitirá posteriormente obter:
#
# URL
# arquivo
# SHA256
# versão
#
# sem depender do jogo.
#
# =============================================================

http_provider_write_metadata()
{
    local INSTALL_PATH="$1"
    local URL="$2"
    local FILENAME="$3"
    local SHA256="${4:-}"
    local VERSION="${5:-current}"

    local META_DIR
    local META_FILE

    META_DIR="${INSTALL_PATH}/.dsm"
    META_FILE="${META_DIR}/http-provider.conf"

    mkdir -p "${META_DIR}"

    {
        printf 'PROVIDER=%q\n' "http"
        printf 'URL=%q\n' "${URL}"
        printf 'FILENAME=%q\n' "${FILENAME}"
        printf 'SHA256=%q\n' "${SHA256}"
        printf 'VERSION=%q\n' "${VERSION}"

    } > "${META_FILE}"

    return 0
}

# =============================================================
# Ler metadata
# =============================================================

http_provider_read_metadata()
{
    local INSTALL_PATH="$1"

    local META_FILE

    META_FILE="${INSTALL_PATH}/.dsm/http-provider.conf"

    if [[ ! -f "${META_FILE}" ]]
    then
        return 1
    fi

    HTTP_PROVIDER_URL=""
    HTTP_PROVIDER_FILENAME=""
    HTTP_PROVIDER_SHA256=""
    HTTP_PROVIDER_VERSION=""

    # Arquivo é produzido exclusivamente pelo próprio DSM.
    # shellcheck source=/dev/null
    source "${META_FILE}"

    HTTP_PROVIDER_URL="${URL:-}"
    HTTP_PROVIDER_FILENAME="${FILENAME:-}"
    HTTP_PROVIDER_SHA256="${SHA256:-}"
    HTTP_PROVIDER_VERSION="${VERSION:-current}"

    return 0
}

# =============================================================
# Install
#
# Contrato universal:
#
# provider_install PACKAGE_ID INSTALL_PATH AUTH
#
# Para HTTP:
#
# PACKAGE_ID = URL
#
# AUTH pode carregar futuramente token/header.
# Nesta primeira versão é ignorado.
#
# Variáveis opcionais:
#
# DSM_HTTP_FILENAME
# DSM_HTTP_SHA256
# DSM_HTTP_VERSION
#
# =============================================================

http_provider_install()
{
    local URL="${1:-}"
    local INSTALL_PATH="${2:-}"
    local AUTH="${3:-}"

    local FILENAME
    local DESTINATION
    local EXPECTED_SHA256
    local VERSION

    if [[ -z "${URL}" ]]
    then
        http_error "URL não informada."
        return 1
    fi

    if [[ -z "${INSTALL_PATH}" ]]
    then
        http_error "Diretório de instalação não informado."
        return 1
    fi

    http_provider_validate_url "${URL}" || return 1
    http_provider_ensure || return 1

    FILENAME="${DSM_HTTP_FILENAME:-}"

    if [[ -z "${FILENAME}" ]]
    then
        FILENAME="$(http_provider_filename "${URL}")"
    fi

    # Nome deve representar somente um arquivo.
    if [[ "${FILENAME}" == */* || "${FILENAME}" == "." || "${FILENAME}" == ".." ]]
    then
        http_error "Nome de arquivo inválido:"
        http_error "${FILENAME}"

        return 1
    fi

    EXPECTED_SHA256="${DSM_HTTP_SHA256:-}"
    VERSION="${DSM_HTTP_VERSION:-current}"

    DESTINATION="${INSTALL_PATH}/${FILENAME}"

    echo
    echo "============================================"
    echo " Capivara - HTTP Provider"
    echo "============================================"
    echo

    echo "URL      : ${URL}"
    echo "Destino  : ${INSTALL_PATH}"
    echo "Arquivo  : ${FILENAME}"
    echo "Versão   : ${VERSION}"
    echo

    mkdir -p "${INSTALL_PATH}"

    # ---------------------------------------------------------
    # Download
    # ---------------------------------------------------------

    if ! http_provider_download \
        "${URL}" \
        "${DESTINATION}"
    then
        return 1
    fi

    # ---------------------------------------------------------
    # Permissão de execução opcional
    # ---------------------------------------------------------

    if [[ "${DSM_HTTP_EXECUTABLE:-0}" == "1" ]]
    then
        http_log "Marcando arquivo como executável:"

        http_log "${DESTINATION}"

        if ! chmod +x "${DESTINATION}"
        then
            http_error "Não foi possível aplicar permissão de execução."
            return 1
        fi
    fi

    # ---------------------------------------------------------
    # Checksum
    # ---------------------------------------------------------

    if ! http_provider_verify_checksum \
        "${DESTINATION}" \
        "${EXPECTED_SHA256}"
    then
        rm -f "${DESTINATION}"
        return 1
    fi

    # ---------------------------------------------------------
    # Metadata
    # ---------------------------------------------------------

    if ! http_provider_write_metadata \
        "${INSTALL_PATH}" \
        "${URL}" \
        "${FILENAME}" \
        "${EXPECTED_SHA256}" \
        "${VERSION}"
    then
        http_error "Falha ao gravar metadata."
        return 1
    fi

    http_log "Instalação HTTP concluída."

    return 0
}

# =============================================================
# Update
#
# Atomic Install cuidará de:
#
# .new
# .old
# rollback
#
# Portanto update no provider equivale a obter novamente
# o pacote solicitado.
#
# =============================================================

http_provider_update()
{
    http_provider_install "$@"
}

# =============================================================
# Verify
#
# IMPORTANTE:
#
# Esta função é somente leitura.
#
# Nunca:
#
# - baixa arquivo
# - altera instalação
# - executa atualização
#
# =============================================================

http_provider_verify()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local EXECUTABLE="${3:-}"

    local FILE
    local FILENAME
    local EXPECTED_SHA256

    if [[ -z "${INSTALL_PATH}" ]]
    then
        http_error "INSTALL_PATH não informado."
        return 1
    fi

    if ! http_provider_read_metadata "${INSTALL_PATH}"
    then
        http_error "Metadata HTTP não encontrada:"
        http_error "${INSTALL_PATH}/.dsm/http-provider.conf"

        return 1
    fi

    FILENAME="${HTTP_PROVIDER_FILENAME}"
    EXPECTED_SHA256="${HTTP_PROVIDER_SHA256}"

    if [[ -z "${FILENAME}" ]]
    then
        http_error "Metadata não contém FILENAME."
        return 1
    fi

    FILE="${INSTALL_PATH}/${FILENAME}"

    if [[ ! -f "${FILE}" ]]
    then
        echo "[ERRO] Pacote HTTP ausente:"
        echo "${FILE}"

        return 1
    fi

    echo "[OK] HTTP package: ${FILENAME}"

    if [[ -n "${EXPECTED_SHA256}" ]]
    then
        if ! http_provider_verify_checksum \
            "${FILE}" \
            "${EXPECTED_SHA256}"
        then
            return 1
        fi
    else
        echo "[OK] HTTP metadata"
    fi

    return 0
}

# =============================================================
# Info
# =============================================================

http_provider_info()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    if ! http_provider_read_metadata "${INSTALL_PATH}"
    then
        echo "provider=http"
        echo "url=${PACKAGE_ID}"
        echo "version=unknown"

        return 1
    fi

    echo "provider=http"
    echo "url=${HTTP_PROVIDER_URL}"
    echo "file=${HTTP_PROVIDER_FILENAME}"
    echo "version=${HTTP_PROVIDER_VERSION:-current}"
}

# =============================================================
# Version
# =============================================================

http_provider_version()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    if ! http_provider_read_metadata "${INSTALL_PATH}"
    then
        echo "unknown"
        return 1
    fi

    echo "${HTTP_PROVIDER_VERSION:-current}"
}

# =============================================================
# API Universal
# =============================================================

provider_ensure()
{
    http_provider_ensure
}

provider_install()
{
    http_provider_install "$@"
}

provider_update()
{
    http_provider_update "$@"
}

provider_verify()
{
    http_provider_verify "$@"
}

provider_info()
{
    http_provider_info "$@"
}

provider_version()
{
    http_provider_version "$@"
}

# =============================================================
# Export API
# =============================================================

export -f http_log
export -f http_error
export -f http_provider_detect_tool
export -f http_provider_ensure
export -f http_provider_validate_url
export -f http_provider_filename
export -f http_provider_download
export -f http_provider_sha256
export -f http_provider_verify_checksum
export -f http_provider_write_metadata
export -f http_provider_read_metadata
export -f http_provider_install
export -f http_provider_update
export -f http_provider_verify
export -f http_provider_info
export -f http_provider_version
export -f provider_ensure
export -f provider_install
export -f provider_update
export -f provider_verify
export -f provider_info
export -f provider_version
