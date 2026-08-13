#!/bin/bash
# =============================================================
# mods/health.sh - MÓDULO 03 (MODS)
# Diagnóstico de saúde dos Mods DSM
# Responsável por:
# - verificar integridade dos mods
# - verificar estado DSM
# - verificar keys
# - gerar status para monitor/dashboard
# NÃO FAZ:
# - download
# - rsync
# - instalação
# - atualização
# - rollback
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
source "${DSM_ROOT}/mods/runtime.sh"

# =============================================================
# Variáveis
# =============================================================
HEALTH_STATUS="healthy"
HEALTH_ERRORS=0
HEALTH_WARNINGS=0

BROKEN_FOLDER=0
MISSING_META=0
INVALID_MODS=0

MOD_COUNT=0
KEY_COUNT=0

# =============================================================
# Registrar erro
# =============================================================
health_error()
{
    HEALTH_STATUS="critical"
    HEALTH_ERRORS=$((HEALTH_ERRORS + 1))
}

# =============================================================
# Registrar warning
# =============================================================
health_warning()
{
    if [ "${HEALTH_STATUS}" = "healthy" ]
    then
        HEALTH_STATUS="warning"
    fi
    HEALTH_WARNINGS=$((HEALTH_WARNINGS + 1))
}

# =============================================================
# Verificar diretórios
# =============================================================
mods_health_directories()
{
    if [ ! -d "${SERVERFILES_PATH}/mods" ]
    then
        log_error \
        "Diretório mods inexistente"
        health_error
    fi

    if [ ! -d "${SERVERFILES_PATH}/keys" ]
    then
        log_warn \
        "Diretório keys inexistente"
        health_warning
    fi
}

# =============================================================
# Verificar mods
# =============================================================
mods_health_mods()
{
    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        WORKSHOP_IDS="$(mods_detect_or_load_workshop_ids || true)"
    fi

    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        log_error \
        "Nenhum mod configurado"
        health_error
        return
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

        if mods_validate_one \
            "${id}" \
            "${folder}" \
            >/dev/null 2>&1
        then
            MOD_COUNT=$((MOD_COUNT + 1))
            echo "[OK] ${folder}"
        else
            echo "[FAIL] ${folder}"
            health_error
            INVALID_MODS=$((INVALID_MODS + 1))
        fi
    done
}

# =============================================================
# Verificar keys
# =============================================================
mods_health_keys()
{
    local count
    count=$(find \
        "${SERVERFILES_PATH}/keys" \
        -name "*.bikey" \
        -type f \
        2>/dev/null \
        | wc -l)

    if [ "${count}" -eq 0 ]
    then
        echo "[WARN] Nenhuma key encontrada"
        health_warning
    else
        echo "[OK] Keys: ${count}"
        KEY_COUNT="$count"
    fi
}

# =============================================================
# Verificar state
# =============================================================
mods_health_state()
{
    if ! declare -F state_list >/dev/null
    then
        log_warn \
        "state.sh indisponível"
        health_warning
        return
    fi

    if ! state_list >/dev/null 2>&1
    then
        log_error \
        "Falha lendo estado dos mods"
        health_error
    fi
}

# =============================================================
# Saúde completa
# =============================================================
mods_health()
{
    section \
    "DSM MOD HEALTH"

    echo
    echo "Status inicial: ${HEALTH_STATUS}"
    echo

    mods_health_directories
    mods_health_mods
    mods_health_keys
    mods_health_state

    echo
    echo "------------------------------------------------------------"
    echo "Status final: ${HEALTH_STATUS}"
    echo "Erros: ${HEALTH_ERRORS}"
    echo "Avisos: ${HEALTH_WARNINGS}"
    echo "------------------------------------------------------------"

     mods_runtime_update \
           "$HEALTH_STATUS" \
           "$MOD_COUNT" \
           "$KEY_COUNT" \
           "$BROKEN_FOLDER" \
           "$MISSING_META" \
           "$INVALID_MODS"

    case "${HEALTH_STATUS}" in
        healthy)
            return 0
        ;;
        warning)
            return 2
        ;;
        critical)
            return 1
        ;;
    esac
}

# =============================================================
# JSON Dashboard
# =============================================================
mods_health_json()
{
cat <<EOF
{
    "module":"mods",
    "status":"${HEALTH_STATUS}",
    "errors":${HEALTH_ERRORS},
    "warnings":${HEALTH_WARNINGS}
}
EOF
}

# =============================================================
# Dispatcher
# =============================================================
health_command()
{
case "${1:-}" in
    check)
        mods_health
    ;;
    json)
        mods_health_json
    ;;
    *)
        echo
        echo "Uso:"
        echo
        echo " health.sh check"
        echo " health.sh json"
        return 1
    ;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    health_command "$@"
fi
