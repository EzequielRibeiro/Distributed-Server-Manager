#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
# Catalog Selection Installation Adapter
# =============================================================
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
CATALOG="${DSM_ROOT}/installer/catalog.sh"
source "${DSM_ROOT}/installer/manager.sh"

selection_error(){ echo "[DSM][SELECTION][ERRO] $*" >&2; }
selection_log(){ echo "[DSM][SELECTION] $*"; }

selection_validate_json()
{
    local JSON="$1"
    jq -e '.schema_version == 2 and .kind == "RuntimeSelection" and (.game|type=="string" and length>0) and (.variant|type=="string" and length>0) and (.provider|type=="string" and length>0) and (.install_dir|type=="string" and startswith("/")) and (.executable|type=="string" and length>0)' >/dev/null <<<"${JSON}"
}

selection_apply_provider_context()
{
    local JSON="$1" STEAM_CONFIG STEAM_APP_ID STEAM_KEY STEAM_VALUE
    unset DSM_STEAM_APP_SET_CONFIG || true
    case "${INSTALL_PROVIDER}" in
        source-build)
            INSTALL_PACKAGE_ID="$(jq -r '.source_repository // .install.repository // empty' <<<"${JSON}")"
            DSM_SOURCE_BUILD_TAG="$(jq -r '.tag // .install.tag // empty' <<<"${JSON}")"
            DSM_SOURCE_BUILD_SYSTEM="$(jq -r '.build_config.system // .install.build_system // "cmake"' <<<"${JSON}")"
            DSM_SOURCE_BUILD_EXECUTABLE="$(jq -r '.executable // .install.executable // empty' <<<"${JSON}")"
            DSM_SOURCE_BUILD_JOBS="$(jq -r '.build_config.jobs // .install.build_jobs // 2' <<<"${JSON}")"
            DSM_SOURCE_BUILD_CMAKE_OPTIONS="$(jq -c '.build_config.options // {}' <<<"${JSON}")"
            export DSM_SOURCE_BUILD_TAG DSM_SOURCE_BUILD_SYSTEM DSM_SOURCE_BUILD_EXECUTABLE DSM_SOURCE_BUILD_JOBS DSM_SOURCE_BUILD_CMAKE_OPTIONS
            ;;
        github)
            INSTALL_PACKAGE_ID="$(jq -r '.source_repository // .install.repository // empty' <<<"${JSON}")"
            DSM_GITHUB_TAG="$(jq -r '.tag // .install.tag // "latest"' <<<"${JSON}")"
            DSM_GITHUB_ASSET="$(jq -r '.asset.name // .install.asset // empty' <<<"${JSON}")"
            export DSM_GITHUB_TAG DSM_GITHUB_ASSET
            ;;
        http|http-archive)
            INSTALL_PACKAGE_ID="$(jq -r '.asset.url // .install.url // empty' <<<"${JSON}")"
            if [[ "${INSTALL_PROVIDER}" == "http" ]]; then DSM_HTTP_FILENAME="$(jq -r '.executable // .asset.name // .install.asset // empty' <<<"${JSON}")"
            else DSM_HTTP_FILENAME="$(jq -r '.asset.name // .install.asset // empty' <<<"${JSON}")"; fi
            DSM_HTTP_VERSION="${GAME_VERSION}"
            DSM_HTTP_SHA256="$(jq -r '.asset.sha256 // .install.sha256 // empty' <<<"${JSON}")"
            DSM_HTTP_ARCHIVE_TYPE="$(jq -r '.archive.type // .install.archive_type // empty' <<<"${JSON}")"
            DSM_HTTP_REFERER="$(jq -r '.request.referer // .install.referer // empty' <<<"${JSON}")"
            DSM_HTTP_ARCHIVE_EXECUTABLE="1"
            export DSM_HTTP_FILENAME DSM_HTTP_VERSION DSM_HTTP_SHA256 DSM_HTTP_ARCHIVE_TYPE DSM_HTTP_ARCHIVE_EXECUTABLE DSM_HTTP_REFERER
            ;;
        local)
            INSTALL_PACKAGE_ID="$(jq -r '.install.package_id // empty' <<<"${JSON}")"
            DSM_LOCAL_VERSION="${GAME_VERSION}"; export DSM_LOCAL_VERSION
            ;;
        steam)
            INSTALL_PACKAGE_ID="$(jq -r '.install.package_id // empty' <<<"${JSON}")"
            STEAM_CONFIG="$(jq -c '.install.steam_app_set_config // null' <<<"${JSON}")"
            if [[ "${STEAM_CONFIG}" != "null" ]]; then
                jq -e 'type=="object" and (.app_id|type=="string" and test("^[0-9]+$")) and (.key|type=="string" and test("^[A-Za-z0-9_.-]+$")) and (.value|type=="string" and test("^[A-Za-z0-9_.-]+$"))' >/dev/null <<<"${STEAM_CONFIG}" || { selection_error "steam_app_set_config inválido."; return 1; }
                STEAM_APP_ID="$(jq -r '.app_id' <<<"${STEAM_CONFIG}")"; STEAM_KEY="$(jq -r '.key' <<<"${STEAM_CONFIG}")"; STEAM_VALUE="$(jq -r '.value' <<<"${STEAM_CONFIG}")"
                [[ "${STEAM_APP_ID}" == "${INSTALL_PACKAGE_ID}" ]] || { selection_error "steam_app_set_config deve pertencer ao AppID instalado."; return 1; }
                DSM_STEAM_APP_SET_CONFIG="${STEAM_APP_ID}:${STEAM_KEY}:${STEAM_VALUE}"; export DSM_STEAM_APP_SET_CONFIG
            fi
            ;;
        *) INSTALL_PACKAGE_ID="$(jq -r '.install.package_id // .source_repository // empty' <<<"${JSON}")" ;;
    esac
    [[ -n "${INSTALL_PACKAGE_ID}" ]] || { selection_error "Seleção não contém PACKAGE_ID resolvível para provider ${INSTALL_PROVIDER}."; return 1; }
}

selection_install_json()
{
    local SELECTION="$1" INSTALL_USER PREVIOUS_VERSION="unknown" VERSION="unknown" ROLLBACK="false"
    selection_validate_json "${SELECTION}" || { selection_error "Selection JSON inválido."; return 1; }
    GAME_ID="$(jq -r '.game' <<<"${SELECTION}")"; GAME_NAME="${GAME_ID}"; GAME_EDITION="$(jq -r '.edition // "default"' <<<"${SELECTION}")"; GAME_VARIANT="$(jq -r '.variant' <<<"${SELECTION}")"
    GAME_VERSION="$(jq -r '.version // "unknown"' <<<"${SELECTION}")"; GAME_BUILD="$(jq -r '.build // .tag // "unknown"' <<<"${SELECTION}")"; PROCESS_ENGINE="$(jq -r '.process_engine // "native"' <<<"${SELECTION}")"
    DSM_INTEGRITY_ARTIFACT_MODE="$(jq -r '.artifact_mode // "executable"' <<<"${SELECTION}")"; INSTALL_PROVIDER="$(jq -r '.provider' <<<"${SELECTION}")"; INSTALL_AUTH="$(jq -r '.auth // "anonymous"' <<<"${SELECTION}")"
    INSTALL_DIR="$(jq -r '.install_dir' <<<"${SELECTION}")"; EXECUTABLE="$(jq -r '.executable' <<<"${SELECTION}")"
    export GAME_ID GAME_NAME GAME_EDITION GAME_VARIANT GAME_VERSION GAME_BUILD PROCESS_ENGINE DSM_INTEGRITY_ARTIFACT_MODE INSTALL_PROVIDER INSTALL_AUTH INSTALL_DIR EXECUTABLE
    selection_apply_provider_context "${SELECTION}" || return 1; export INSTALL_PACKAGE_ID
    if [[ "${INSTALL_PROVIDER}" == "steam" && "${INSTALL_AUTH}" == "anonymous" ]]; then INSTALL_USER="anonymous"
    elif [[ "${INSTALL_PROVIDER}" == "steam" ]]; then INSTALL_USER="${DSM_STEAM_USER:-}"; [[ -n "${INSTALL_USER}" ]] || { selection_error "Este jogo exige autenticação Steam. Configure DSM_STEAM_USER no serviço da Dashboard."; return 1; }
    else INSTALL_USER="$(install_manager_resolve_user)" || return 1; fi
    provider_require "${INSTALL_PROVIDER}" || return 1
    if [[ -d "${INSTALL_DIR}" ]]; then PREVIOUS_VERSION="$(install_manager_provider_version "${INSTALL_PACKAGE_ID}" "${INSTALL_DIR}")"; fi
    echo; echo "============================================"; echo " Capivara - Catalog Installation"; echo "============================================"; echo
    echo "Game     : ${GAME_ID}"; echo "Edition  : ${GAME_EDITION}"; echo "Variant  : ${GAME_VARIANT}"; echo "Version  : ${GAME_VERSION}"; echo "Build    : ${GAME_BUILD}"; echo "Engine   : ${PROCESS_ENGINE}"; echo "Artifact : ${EXECUTABLE} (${DSM_INTEGRITY_ARTIFACT_MODE})"; echo "Provider : ${INSTALL_PROVIDER}"; echo "Destino  : ${INSTALL_DIR}"; echo
    install_manager_publish_state "${GAME_ID}" "install" "running" "installing"; install_manager_event install_event_install_started "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}"
    if atomic_install "${INSTALL_PROVIDER}" "${GAME_ID}" "${INSTALL_PACKAGE_ID}" "${INSTALL_DIR}" "${EXECUTABLE}" "${INSTALL_USER}"; then
        mkdir -p "${INSTALL_DIR}/.dsm"; jq . <<<"${SELECTION}" > "${INSTALL_DIR}/.dsm/catalog-selection.json"
        VERSION="$(install_manager_provider_version "${INSTALL_PACKAGE_ID}" "${INSTALL_DIR}")"; ROLLBACK="$(install_manager_rollback_status "${INSTALL_DIR}")"
        install_manager_publish_state "${GAME_ID}" "install" "success" "healthy"; install_manager_event install_event_install_completed "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}" "${VERSION}" "${ROLLBACK}"
        selection_log "Instalação dinâmica concluída."; selection_log "Selection snapshot: ${INSTALL_DIR}/.dsm/catalog-selection.json"; return 0
    fi
    install_error_handle_atomic "install" "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}"; return 1
}

selection_prepare_and_install(){ local ENVIRONMENT_ID="$1" SELECTOR="$2" SELECTION; SELECTION="$("${CATALOG}" runtime prepare "${ENVIRONMENT_ID}" "${SELECTOR}" --json)" || return 1; selection_install_json "${SELECTION}"; }
usage(){ cat <<'EOF'
Uso:
  install_selection.sh install ENVIRONMENT_ID SELECTOR
  install_selection.sh install-json FILE.json
  install_selection.sh show ENVIRONMENT_ID SELECTOR
EOF
}
case "${1:-}" in
 install) [[ $# -eq 3 ]] || { usage; exit 2; }; selection_prepare_and_install "$2" "$3" ;;
 install-json) [[ $# -eq 2 && -f "$2" ]] || { usage; exit 2; }; selection_install_json "$(cat "$2")" ;;
 show) [[ $# -eq 3 ]] || { usage; exit 2; }; "${CATALOG}" runtime prepare "$2" "$3" --json ;;
 *) usage; exit 2 ;;
esac
