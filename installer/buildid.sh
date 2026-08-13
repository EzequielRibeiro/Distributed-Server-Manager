#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Installation Manager - Build ID
#
# Responsável:
# - localizar manifest Steam
# - obter BuildID instalado
# - fornecer API para outros módulos
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


install_manifest_path()
{
    local INSTALL_PATH="$1"
    local APP_ID="$2"

    echo "${INSTALL_PATH}/steamapps/appmanifest_${APP_ID}.acf"
}


install_buildid()
{
    local INSTALL_PATH="$1"
    local APP_ID="$2"

    local MANIFEST

    MANIFEST="$(install_manifest_path "${INSTALL_PATH}" "${APP_ID}")"

    if [[ ! -f "${MANIFEST}" ]]
    then
        echo "0"
        return 1
    fi

    local BUILD_ID

    BUILD_ID="$(
        awk -F'"' '
            /"buildid"/ {
                print $4
                exit
            }
        ' "${MANIFEST}"
    )"

    if [[ -z "${BUILD_ID}" ]]
    then
        echo "0"
        return 1
    fi

    echo "${BUILD_ID}"
}


install_buildid_info()
{
    local INSTALL_PATH="$1"
    local APP_ID="$2"

    local BUILD_ID

    BUILD_ID="$(install_buildid "${INSTALL_PATH}" "${APP_ID}" 2>/dev/null || echo 0)"

    cat <<EOF
{
  "appid": "${APP_ID}",
  "buildid": "${BUILD_ID}",
  "manifest": "$(install_manifest_path "${INSTALL_PATH}" "${APP_ID}")"
}
EOF
}


export -f install_manifest_path
export -f install_buildid
export -f install_buildid_info