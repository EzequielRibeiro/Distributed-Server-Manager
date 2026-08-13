#!/bin/bash
# =============================================================
# DSM Dashboard API v1.2.0
# Arquivo: dashboard/api/alerts_count.sh
# Função: Retornar resumo estatístico dos alertas DSM
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
ALERT_MANAGER="$DSM_ROOT/monitor/alertmanager.sh"

# -------------------------------------------------------------
# Verifica Alert Manager
# -------------------------------------------------------------
if [ ! -x "$ALERT_MANAGER" ]; then
cat <<EOF
{
 "error":"Alert Manager indisponível"
}
EOF
exit 1
fi

# -------------------------------------------------------------
# Obtém JSON dos alertas
# -------------------------------------------------------------
ALERTS_JSON=$("$ALERT_MANAGER" json 2>/dev/null)

# -------------------------------------------------------------
# Se não existir jq
# -------------------------------------------------------------
if ! command -v jq >/dev/null 2>&1
then
cat <<EOF
{
 "error":"jq não instalado"
}
EOF
exit 1
fi

# -------------------------------------------------------------
# Contadores
# -------------------------------------------------------------
TOTAL=$(echo "$ALERTS_JSON" | jq 'length')
OPEN=$(echo "$ALERTS_JSON" | jq '[.[] | select(.state=="OPEN")] | length')
ACK=$(echo "$ALERTS_JSON" | jq '[.[] | select(.state=="ACKNOWLEDGED")] | length')
RESOLVED=$(echo "$ALERTS_JSON" | jq '[.[] | select(.state=="RESOLVED")] | length')
SUPPRESSED=$(echo "$ALERTS_JSON" | jq '[.[] | select(.state=="SUPPRESSED")] | length')
CRITICAL=$(echo "$ALERTS_JSON" | jq '[.[] | select(.level=="CRITICAL" and (.state=="OPEN" or .state=="ACKNOWLEDGED"))] | length')
WARNING=$(echo "$ALERTS_JSON" | jq '[.[] | select(.level=="WARNING" and (.state=="OPEN" or .state=="ACKNOWLEDGED"))] | length')

# -------------------------------------------------------------
# Determina estado geral
# -------------------------------------------------------------
STATUS="OK"
if [ "$CRITICAL" -gt 0 ]
then
    STATUS="CRITICAL"
elif [ "$WARNING" -gt 0 ]
then
    STATUS="WARNING"
fi

# -------------------------------------------------------------
# Retorno JSON
# -------------------------------------------------------------
cat <<EOF
{
 "status":"$STATUS",
 "total":$TOTAL,
 "open":$OPEN,
 "critical":$CRITICAL,
 "warning":$WARNING,
 "acknowledged":$ACK,
 "resolved":$RESOLVED,
 "suppressed":$SUPPRESSED,
 "timestamp":"$(date -Iseconds)"
}
EOF
