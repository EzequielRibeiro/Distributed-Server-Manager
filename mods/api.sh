#!/bin/bash
# =============================================================
# mods/api.sh - MÓDULO 03 (MODS)
# API JSON dos Mods DSM
# Responsável por:
# - fornecer dados JSON
# - integrar Dashboard
# - fornecer informações externas
# NÃO FAZ:
# - instalação
# - atualização
# - sincronização
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Dependências
# =============================================================
source "${DSM_ROOT}/mods/status.sh"
source "${DSM_ROOT}/mods/state.sh"
source "${DSM_ROOT}/mods/validator.sh"

# =============================================================
# Helpers JSON
# =============================================================
json_escape()
{
    echo "$1" \
    | sed \
    's/\\/\\\\/g;
     s/"/\\"/g'
}

# =============================================================
# API Status
# dsm mods api status
# =============================================================
mods_api_status()
{
    local installed
    installed="$(mods_status_count)"

    local import
    import="$(mods_status_import)"

    local backup
    backup="$(mods_status_backup)"

    local validation
    if mods_validate
    then
        validation="OK"
    else
        validation="ERROR"
    fi

cat <<EOF
{
    "module":"mods",
    "status":"online",
    "installed":${installed},
    "import":"${import}",
    "backup":"${backup}",
    "validation":"${validation}",
    "workshop_ids":"$(json_escape "${WORKSHOP_IDS:-}")"
}
EOF
}

# =============================================================
# API Lista
# =============================================================
mods_api_list()
{
    echo "["
    local first=true
    if [ -d "${SERVERFILES_PATH}/mods" ]
    then
        while read -r mod
        do
            if [ "${first}" = true ]
            then
                first=false
            else
                echo ","
            fi

            cat <<EOF
{
    "name":"$(basename "${mod}")",
    "path":"${mod}"
}
EOF
        done < <(
            find "${SERVERFILES_PATH}/mods" \
            -maxdepth 1 \
            -type d \
            -name "@*" \
            | sort
        )
    fi
    echo
    echo "]"
}

# =============================================================
# API Estado
# =============================================================
mods_api_state()
{
cat <<EOF
{
    "module":"mods",
    "state":"$(state_status 2>/dev/null || echo unknown)"
}
EOF
}

# =============================================================
# API Completa
# =============================================================
mods_api_all()
{
cat <<EOF
{
    "module":"mods",
    "status":
EOF

mods_api_status
echo ","
echo '"mods":'
mods_api_list
echo
echo "}"
}

# =============================================================
# Dispatcher
# =============================================================
api_command()
{
case "${1:-}" in
status)
    mods_api_status
;;
list)
    mods_api_list
;;
state)
    mods_api_state
;;
all)
    mods_api_all
;;
*)
    echo
    echo "Uso:"
    echo
    echo " api.sh status"
    echo " api.sh list"
    echo " api.sh state"
    echo " api.sh all"
    return 1
;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    api_command "$@"
fi
