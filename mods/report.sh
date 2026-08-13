#!/bin/bash
# =============================================================
# mods/report.sh - MÓDULO 03 (MODS)
# Relatório dos Mods DSM
# Responsável por:
# - listar mods instalados
# - mostrar Workshop ID
# - mostrar estado
# - mostrar validação
# NÃO FAZ:
# - SteamCMD
# - rsync
# - instalação
# - atualização
# - alteração de estado
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
source "${DSM_ROOT}/mods/state.sh"
source "${DSM_ROOT}/mods/detector.sh"
source "${DSM_ROOT}/mods/validator.sh"

# =============================================================
# Cabeçalho
# =============================================================
mods_report_header()
{
cat <<EOF

============================================================
 DSM MOD REPORT
============================================================

EOF
}

# =============================================================
# Converter timestamp
# =============================================================
mods_report_date()
{
    local ts="$1"
    if [ -z "${ts}" ] || [ "${ts}" = "0" ]
    then
        echo "desconhecido"
        return
    fi
    date \
    -d "@${ts}" \
    "+%Y-%m-%d %H:%M:%S" \
    2>/dev/null || echo "${ts}"
}

# =============================================================
# Relatório individual
# Uso:
# mods_report_one ID @MOD
# =============================================================
mods_report_one()
{
    local id="$1"
    local folder="$2"
    local timestamp
    timestamp="$(state_get_timestamp "${id}")"
    local state

    if [ -n "${timestamp}" ]
    then
        state="INSTALADO"
    else
        state="SEM ESTADO"
    fi

    echo
    echo "Mod:"
    echo "------------------------------------------------------------"
    echo "Nome........: ${folder}"
    echo "Workshop ID.: ${id}"
    echo "Estado......: ${state}"
    echo "Atualizado..: $(mods_report_date "${timestamp}")"

    if mods_validate_one \
        "${id}" \
        "${folder}" \
        >/dev/null 2>&1
    then
        echo "Validação...: OK"
    else
        echo "Validação...: FALHA"
    fi
}

# =============================================================
# Relatório completo
# =============================================================
mods_report()
{
    mods_report_header
    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        WORKSHOP_IDS="$(mods_detect_or_load_workshop_ids || true)"
    fi

    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        log_error \
        "Nenhum mod encontrado."
        return 1
    fi

    IFS=';' read -ra MOD_LIST <<< "${WORKSHOP_IDS}"
    local item
    for item in "${MOD_LIST[@]}"
    do
        local id
        local folder
        id="${item%%:*}"
        folder="${item##*:}"
        id="$(echo "${id}" | xargs)"
        folder="$(echo "${folder}" | xargs)"
        [ -z "${id}" ] && continue

        mods_report_one \
            "${id}" \
            "${folder}"
    done
    echo
    echo "============================================================"
}

# =============================================================
# Saída JSON
# Futuro Dashboard/API
# =============================================================
mods_report_json()
{
cat <<EOF
{
    "module":"mods",
    "status":"ok"
}
EOF
}

# =============================================================
# Dispatcher
# =============================================================
report_command()
{
case "${1:-}" in
    list)
        mods_report
    ;;
    json)
        mods_report_json
    ;;
    *)
        echo
        echo "Uso:"
        echo
        echo " report.sh list"
        echo " report.sh json"
        return 1
    ;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    report_command "$@"
fi
