#!/usr/bin/env bash
# =============================================================
# DSM Mods Worker
# Validação periódica dos Mods
# Responsável: Ler mods via integração LinuxGSM
# Atualiza: dashboard/state/mods_state.json
# =============================================================

set -Eeuo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_INTERVAL="${DSM_INTERVAL:-3600}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
OUTPUT="${STATE_DIR}/mods_state.json"
CONFIG="${DSM_ROOT}/config/dsm.conf"
CORE="${DSM_ROOT}/core/lgsm.sh"

mkdir -p "$STATE_DIR"

# -------------------------------------------------------------
# Carregar configuração DSM
# -------------------------------------------------------------
if [[ -f "$CONFIG" ]]
then
    source "$CONFIG"
fi

# -------------------------------------------------------------
# Carregar integração LinuxGSM
# -------------------------------------------------------------
if [[ -f "$CORE" ]]
then
    source "$CORE"
else
    echo "Erro: core/lgsm.sh não encontrado"
    exit 1
fi

# -------------------------------------------------------------
# Coleta de Mods
# -------------------------------------------------------------
collect_mods() {
    local MOD_DIR
    local TOTAL=0
    local FIRST=true
    local NAME

    MOD_DIR="$(lgsm_mods_dir)"
    mkdir -p "$STATE_DIR"

    # Diretório inexistente
    if [[ ! -d "$MOD_DIR" ]]
    then
        cat > "$OUTPUT" <<EOF
{
    "status":"error",
    "message":"Diretório de mods não encontrado",
    "total":0,
    "mods":[],
    "updated_at":$(date +%s)
}
EOF
        return 1
    fi

    {
        echo "{"
        echo "  \"status\":\"ok\","
        echo "  \"message\":\"Mods coletados com sucesso\","
        echo "  \"total\":0,"
        echo "  \"mods\":["
        for MOD in "$MOD_DIR"/*
        do
            [[ -d "$MOD" ]] || continue
            NAME="$(basename "$MOD")"
            if [[ "$FIRST" == true ]]
            then
                FIRST=false
            else
                echo ","
            fi
            cat <<EOF
    {
        "name":"$NAME",
        "status":"ok"
    }
EOF
            TOTAL=$((TOTAL + 1))
        done
        echo
        echo "  ],"
        echo "  \"updated_at\":$(date +%s)"
        echo "}"
    } > "${OUTPUT}.tmp"

    sed -i "s/\"total\":0/\"total\":${TOTAL}/" "${OUTPUT}.tmp"
    mv "${OUTPUT}.tmp" "$OUTPUT"
}

# -------------------------------------------------------------
# Loop principal
# -------------------------------------------------------------
while true
do
    if ! collect_mods
    then
        echo "[$(date)] Falha ao atualizar mods_state.json" >&2
    fi
    sleep "$DSM_INTERVAL"
done
