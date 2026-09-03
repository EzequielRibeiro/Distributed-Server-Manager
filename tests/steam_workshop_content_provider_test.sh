#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

export DSM_ROOT="${ROOT}"
# shellcheck source=/dev/null
source "${ROOT}/installer/providers/steam-workshop.sh"

# Replace only the external SteamCMD boundary. The provider logic, parsing,
# staging copy and metadata generation remain the production implementation.
STEAMCMD_ROOT="${TMP}/steamcmd"
STEAMCMD_BIN="${TMP}/steamcmd/steamcmd.sh"
mkdir -p "${STEAMCMD_ROOT}"
printf '#!/usr/bin/env bash\nexit 0\n' >"${STEAMCMD_BIN}"
chmod +x "${STEAMCMD_BIN}"

steam_provider_validate(){ return 0; }
steam_progress_publish(){ :; }
steamcmd_run_with_progress()
{
    local APP="" ITEM="" PREV=""
    for ARG in "$@"; do
        if [[ "${PREV}" == "+workshop_download_item" ]]; then APP="${ARG}"; PREV="workshop-app"; continue; fi
        if [[ "${PREV}" == "workshop-app" ]]; then ITEM="${ARG}"; PREV=""; continue; fi
        PREV="${ARG}"
    done
    [[ "${APP}" == "221100" && "${ITEM}" == "1559212036" ]] || return 9
    mkdir -p "${STEAMCMD_ROOT}/steamapps/workshop/content/${APP}/${ITEM}/Keys"
    printf 'fixture' >"${STEAMCMD_ROOT}/steamapps/workshop/content/${APP}/${ITEM}/mod.cpp"
    printf 'key' >"${STEAMCMD_ROOT}/steamapps/workshop/content/${APP}/${ITEM}/Keys/example.bikey"
}

DEST="${TMP}/installed"
workshop_provider_install "221100:1559212036" "${DEST}" anonymous
[[ -f "${DEST}/mod.cpp" ]]
[[ -f "${DEST}/Keys/example.bikey" ]]
jq -e '.kind=="SteamWorkshopArtifact" and .workshop_app_id=="221100" and .published_file_id=="1559212036"' \
    "${DEST}/.dsm/workshop.json" >/dev/null
workshop_provider_verify "221100:1559212036" "${DEST}"

export DSM_WORKSHOP_APP_ID=108600
export DSM_WORKSHOP_ITEM_ID=123456789
PARSED="$(workshop_parse_package ignored)"
[[ "${PARSED}" == $'108600\t123456789' ]]
unset DSM_WORKSHOP_APP_ID DSM_WORKSHOP_ITEM_ID

if workshop_parse_package '221100;rm -rf /' >/dev/null 2>&1; then
    echo 'FAIL: unsafe Workshop package accepted' >&2
    exit 1
fi

echo 'Steam Workshop content provider tests passed.'
