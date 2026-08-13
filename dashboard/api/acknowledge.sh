#!/bin/bash
# =============================================================
# DSM Dashboard API v1.2.0
# Arquivo: dashboard/api/acknowledge.sh
# Função: Reconhecimento manual de alertas pelo Dashboard
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_MANAGER="$DSM_ROOT/core/alert_state.sh"
NOTIFICATION_CENTER="$DSM_ROOT/core/notification_center.sh"

# -------------------------------------------------------------
# Cabeçalho HTTP
# -------------------------------------------------------------
api_header() {
    echo "Content-Type: application/json"
    echo ""
}

# -------------------------------------------------------------
# Resposta JSON
# -------------------------------------------------------------
json_response() {
cat <<EOF
{
  "success": $1,
  "message": "$2"
}
EOF
}

# -------------------------------------------------------------
# Obter parâmetro id
# Aceita: QUERY_STRING: id=host-cpu ou: acknowledge.sh host-cpu
# -------------------------------------------------------------
get_alert_id() {
    if [ -n "$1" ]; then
        echo "$1"
        return
    fi

    echo "$QUERY_STRING" | tr '&' '\n' | awk -F= '/^id=/{print $2}'
}

# -------------------------------------------------------------
# Reconhecer alerta
# -------------------------------------------------------------
acknowledge_alert() {
    local id="$1"

    if [ -z "$id" ]; then
        json_response false "ID do alerta não informado"
        return 1
    fi

    # Verifica se existe
    local exists
    exists=$("$STATE_MANAGER" get "$id" | jq -r '.id // empty')

    if [ -z "$exists" ]; then
        json_response false "Alerta inexistente"
        return 1
    fi

    # Alterar estado
    if "$STATE_MANAGER" set "$id" ACKNOWLEDGED
    then
        # Atualiza Notification Center
        "$NOTIFICATION_CENTER" ack "$id"
        json_response true "Alerta reconhecido"
    else
        json_response false "Não foi possível reconhecer alerta"
    fi
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
case "$REQUEST_METHOD" in
POST|"")
    api_header
    ALERT_ID=$(get_alert_id "$1")
    acknowledge_alert "$ALERT_ID"
;;
*)
    api_header
    json_response false "Método não permitido"
;;
esac
