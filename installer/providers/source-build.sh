#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
# Installation Provider - Source Build
#
# Provider genérico para builds controlados a partir de código-fonte.
#
# PACKAGE_ID:
#   owner/repository
#
# Configuração:
#   DSM_SOURCE_BUILD_TAG
#   DSM_SOURCE_BUILD_SYSTEM=cmake
#   DSM_SOURCE_BUILD_EXECUTABLE
#
# Segurança:
#   - não executa shell arbitrário vindo do catálogo
#   - repositório deve usar owner/repository
#   - tag/ref é validada
#   - build ocorre em diretório temporário
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/installer/provider_progress.sh"

SOURCE_BUILD_REPOSITORY=""
SOURCE_BUILD_TAG=""
SOURCE_BUILD_COMMIT=""
SOURCE_BUILD_SYSTEM=""
SOURCE_BUILD_EXECUTABLE=""

source_build_log()
{
    echo "[DSM][SOURCE-BUILD] $*"
}

source_build_error()
{
    echo "[DSM][SOURCE-BUILD][ERRO] $*" >&2
}

source_build_validate_repository()
{
    local REPO="${1:-}"

    [[ "${REPO}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
}

source_build_validate_ref()
{
    local REF="${1:-}"

    [[ -n "${REF}" ]] || return 1

    # Bloqueia opções e caracteres que não são necessários
    # para tags/branches/commits normais.
    [[ "${REF}" != -* ]] || return 1
    [[ "${REF}" =~ ^[A-Za-z0-9._/+:-]+$ ]]
}

source_build_validate_relative_path()
{
    local VALUE="${1:-}"

    [[ -n "${VALUE}" ]] || return 1
    [[ "${VALUE}" != /* ]] || return 1
    [[ "${VALUE}" != *".."* ]] || return 1
    [[ "${VALUE}" =~ ^[A-Za-z0-9._/+:-]+$ ]]
}

source_build_provider_ensure()
{
    local REQUIRED=(
        git
        cmake
        make
        g++
        sha256sum
    )

    local CMD
    local MISSING=()

    for CMD in "${REQUIRED[@]}"
    do
        command -v "${CMD}" >/dev/null 2>&1 ||
            MISSING+=("${CMD}")
    done

    if (( ${#MISSING[@]} > 0 ))
    then
        source_build_error \
            "Dependências de build ausentes: ${MISSING[*]}"
        return 1
    fi

    return 0
}

source_build_write_metadata()
{
    local INSTALL_PATH="$1"
    local REPOSITORY="$2"
    local TAG="$3"
    local COMMIT="$4"
    local BUILD_SYSTEM="$5"
    local EXECUTABLE="$6"

    mkdir -p "${INSTALL_PATH}/.dsm"

    {
        printf 'PROVIDER=%q\n' "source-build"
        printf 'REPOSITORY=%q\n' "${REPOSITORY}"
        printf 'TAG=%q\n' "${TAG}"
        printf 'COMMIT=%q\n' "${COMMIT}"
        printf 'BUILD_SYSTEM=%q\n' "${BUILD_SYSTEM}"
        printf 'EXECUTABLE=%q\n' "${EXECUTABLE}"
    } > "${INSTALL_PATH}/.dsm/source-build-provider.conf"
}

source_build_read_metadata()
{
    local INSTALL_PATH="$1"
    local FILE="${INSTALL_PATH}/.dsm/source-build-provider.conf"

    [[ -f "${FILE}" ]] || return 1

    REPOSITORY=""
    TAG=""
    COMMIT=""
    BUILD_SYSTEM=""
    EXECUTABLE=""

    # Arquivo produzido exclusivamente pelo Capivara.
    # shellcheck source=/dev/null
    source "${FILE}"

    SOURCE_BUILD_REPOSITORY="${REPOSITORY:-}"
    SOURCE_BUILD_TAG="${TAG:-}"
    SOURCE_BUILD_COMMIT="${COMMIT:-}"
    SOURCE_BUILD_SYSTEM="${BUILD_SYSTEM:-}"
    SOURCE_BUILD_EXECUTABLE="${EXECUTABLE:-}"
}

source_build_cmake_options()
{
    local JSON="${DSM_SOURCE_BUILD_CMAKE_OPTIONS:-}"

    if [[ -z "${JSON}" ]]
    then
        JSON='{}'
    fi

    if ! jq -e '
        type == "object"
        and all(
            keys[];
            test("^[A-Z][A-Z0-9_]*$")
        )
        and all(
            .[];
            type == "string"
            and test("^[A-Za-z0-9_./:+-]*$")
        )
    ' >/dev/null 2>&1 <<<"${JSON}"
    then
        source_build_error "Opções CMake inválidas."
        return 1
    fi

    local KEY VALUE

    while IFS=$'\t' read -r KEY VALUE
    do
        [[ -n "${KEY}" ]] || continue
        printf '%s\0' "-D${KEY}=${VALUE}"
    done < <(
        jq -r '
            to_entries[]
            | [.key, .value]
            | @tsv
        ' <<<"${JSON}"
    )
}

source_build_provider_install()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local AUTH="${3:-}"
    local EXPECTED_EXECUTABLE="${4:-${DSM_EXPECTED_EXECUTABLE:-}}"

    local TAG="${DSM_SOURCE_BUILD_TAG:-}"
    local BUILD_SYSTEM="${DSM_SOURCE_BUILD_SYSTEM:-cmake}"
    local EXECUTABLE="${DSM_SOURCE_BUILD_EXECUTABLE:-${EXPECTED_EXECUTABLE}}"

    local WORK_ROOT=""
    local SOURCE_DIR=""
    local BUILD_DIR=""
    local COMMIT=""

    source_build_provider_ensure || return 1

    if ! source_build_validate_repository "${PACKAGE_ID}"
    then
        source_build_error \
            "PACKAGE_ID inválido. Use owner/repository."
        return 1
    fi

    if ! source_build_validate_ref "${TAG}"
    then
        source_build_error "Tag/ref inválida: ${TAG}"
        return 1
    fi

    if [[ "${BUILD_SYSTEM}" != "cmake" ]]
    then
        source_build_error \
            "Build system não suportado: ${BUILD_SYSTEM}"
        return 1
    fi

    if ! source_build_validate_relative_path "${EXECUTABLE}"
    then
        source_build_error \
            "Caminho de executável inválido: ${EXECUTABLE}"
        return 1
    fi

    if [[ -z "${INSTALL_PATH}" || "${INSTALL_PATH}" == "/" ]]
    then
        source_build_error "Diretório de instalação inválido."
        return 1
    fi

    WORK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/capivara-source-build.XXXXXX")" ||
        return 1

    SOURCE_DIR="${WORK_ROOT}/source"
    BUILD_DIR="${WORK_ROOT}/build"

    trap 'rm -rf -- "${WORK_ROOT}"' RETURN

    provider_progress_publish \
        "preparing" 20 \
        "Preparando código-fonte"

    source_build_log "Repositório : ${PACKAGE_ID}"
    source_build_log "Ref         : ${TAG}"
    source_build_log "Build       : ${BUILD_SYSTEM}"

    git clone \
        --quiet \
        --filter=blob:none \
        "https://github.com/${PACKAGE_ID}.git" \
        "${SOURCE_DIR}" ||
        return 1

    git -C "${SOURCE_DIR}" \
        checkout \
        --quiet \
        --detach \
        "${TAG}" ||
        return 1

    COMMIT="$(
        git -C "${SOURCE_DIR}" rev-parse HEAD
    )" || return 1

    provider_progress_publish \
        "building" 35 \
        "Configurando build CMake"

    mkdir -p "${BUILD_DIR}" "${INSTALL_PATH}"

    local CMAKE_OPTIONS=()

    while IFS= read -r -d '' OPTION
    do
        CMAKE_OPTIONS+=("${OPTION}")
    done < <(source_build_cmake_options) || return 1

    cmake \
        -S "${SOURCE_DIR}" \
        -B "${BUILD_DIR}" \
        -DCMAKE_BUILD_TYPE=Release \
        "${CMAKE_OPTIONS[@]}" ||
        return 1

    provider_progress_publish \
        "building" 50 \
        "Compilando código-fonte"

    cmake \
        --build "${BUILD_DIR}" \
        --parallel "${DSM_SOURCE_BUILD_JOBS:-2}" ||
        return 1

    provider_progress_publish \
        "installing" 68 \
        "Instalando build no staging"

    cmake \
        --install "${BUILD_DIR}" \
        --prefix "${INSTALL_PATH}" ||
        return 1

    if [[ ! -f "${INSTALL_PATH}/${EXECUTABLE}" ]]
    then
        source_build_error \
            "Executável esperado não encontrado: ${INSTALL_PATH}/${EXECUTABLE}"
        return 1
    fi

    chmod +x "${INSTALL_PATH}/${EXECUTABLE}" ||
        return 1

    source_build_write_metadata \
        "${INSTALL_PATH}" \
        "${PACKAGE_ID}" \
        "${TAG}" \
        "${COMMIT}" \
        "${BUILD_SYSTEM}" \
        "${EXECUTABLE}" ||
        return 1

    provider_progress_publish \
        "built" 75 \
        "Build concluído"

    source_build_log "Commit: ${COMMIT}"

    return 0
}

source_build_provider_update()
{
    source_build_provider_install "$@"
}

source_build_provider_verify()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local EXECUTABLE="${3:-}"

    source_build_read_metadata "${INSTALL_PATH}" || {
        source_build_error "Metadata source-build não encontrada."
        return 1
    }

    if [[ -z "${EXECUTABLE}" ]]
    then
        EXECUTABLE="${SOURCE_BUILD_EXECUTABLE}"
    fi

    source_build_validate_relative_path "${EXECUTABLE}" ||
        return 1

    [[ -f "${INSTALL_PATH}/${EXECUTABLE}" ]] ||
        return 1

    [[ -x "${INSTALL_PATH}/${EXECUTABLE}" ]] ||
        return 1

    return 0
}

source_build_provider_info()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    source_build_read_metadata "${INSTALL_PATH}" ||
        return 1

    printf 'provider=source-build\n'
    printf 'repository=%s\n' "${SOURCE_BUILD_REPOSITORY}"
    printf 'tag=%s\n' "${SOURCE_BUILD_TAG}"
    printf 'commit=%s\n' "${SOURCE_BUILD_COMMIT}"
    printf 'build_system=%s\n' "${SOURCE_BUILD_SYSTEM}"
    printf 'executable=%s\n' "${SOURCE_BUILD_EXECUTABLE}"
}

source_build_provider_version()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    source_build_read_metadata "${INSTALL_PATH}" ||
        return 1

    if [[ -n "${SOURCE_BUILD_TAG}" ]]
    then
        printf '%s\n' "${SOURCE_BUILD_TAG}"
    else
        printf '%s\n' "${SOURCE_BUILD_COMMIT}"
    fi
}

# =============================================================
# Universal Provider Contract
# =============================================================

provider_ensure()
{
    source_build_provider_ensure "$@"
}

provider_install()
{
    source_build_provider_install "$@"
}

provider_update()
{
    source_build_provider_update "$@"
}

provider_verify()
{
    source_build_provider_verify "$@"
}

provider_info()
{
    source_build_provider_info "$@"
}

provider_version()
{
    source_build_provider_version "$@"
}
