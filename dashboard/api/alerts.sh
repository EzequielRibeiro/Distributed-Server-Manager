#!/bin/bash
# =============================================================
# DSM Dashboard API v1.2.0
# Arquivo: dashboard/api/alerts.sh
# Função: API REST de alertas do DSM
# Uso: alerts.sh list, active, critical, count
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
ALERT_MANAGER="$DSM_ROOT/monitor/alertmanager.sh"

# -------------------------------------------------------------
# Verifica dependência
# -------------------------------------------------------------
check_dependency() {
    if [ ! -x "$ALERT_MANAGER" ]; then
        echo '{"error":"Alert Manager não encontrado"}'
        exit 1
    fi
}

# -------------------------------------------------------------
# Lista todos os alertas
# -------------------------------------------------------------
alerts_list() {
    "$ALERT_MANAGER" json
}

# -------------------------------------------------------------
# Lista somente alertas ativos (OPEN + ACKNOWLEDGED)
# -------------------------------------------------------------
alerts_active() {
cat <<EOF
[
EOF

local first=1

"$ALERT_MANAGER" json | jq -c '.[]' 2>/dev/null |
while read alert
do
    state=$(echo "$alert" | jq -r '.state')
    if [ "$state" = "OPEN" ] || [ "$state" = "ACKNOWLEDGED" ]
    then
        if [ "$first" -eq 0 ]; then
            echo ","
        fi
        first=0
        echo "$alert"
    fi
done
echo "]"
}

# -------------------------------------------------------------
# Alertas críticos
# -------------------------------------------------------------
alerts_critical() {
cat <<EOF
[
EOF

local first=1

"$ALERT_MANAGER" json | jq -c '.[]' 2>/dev/null |
while read alert
do
    level=$(echo "$alert" | jq -r '.level')
    if [ "$level" = "CRITICAL" ]
    then
        if [ "$first" -eq 0 ]; then
            echo ","
        fi
        first=0
        echo "$alert"
    fi
done
echo "]"
}

# -------------------------------------------------------------
# Contador de alertas
# -------------------------------------------------------------
alerts_count() {
    local total
    local critical
    local warning

    total=$("$ALERT_MANAGER" count OPEN)
    critical=$("$ALERT_MANAGER" json | jq '[.[] | select(.level=="CRITICAL")] | length')
    warning=$("$ALERT_MANAGER" json | jq '[.[] | select(.level=="WARNING")] | length')

cat <<EOF
{
 "total": $total,
 "critical": $critical,
 "warning": $warning
}
EOF
}

# -------------------------------------------------------------
# Health resumido
# -------------------------------------------------------------
alerts_health() {
    local critical
    critical=$("$ALERT_MANAGER" json | jq '[.[] | select(.state=="OPEN" and .level=="CRITICAL")] | length')

    if [ "$critical" -gt 0 ]
    then
        status="CRITICAL"
    else
        status="OK"
    fi

cat <<EOF
{
 "status":"$status",
 "critical_alerts":$critical
}
EOF
}

# -------------------------------------------------------------
# Router API
# -------------------------------------------------------------
case "$1" in
list)
    check_dependency
    alerts_list
;;
active)
    check_dependency
    alerts_active
;;
critical)
    check_dependency
    alerts_critical
;;
count)
    check_dependency
    alerts_count
;;
health)
    check_dependency
    alerts_health
;;
*)
cat <<EOF
{
 "error":"ação inválida",
 "available":[
   "list",
   "active",
   "critical",
   "count",
   "health"
 ]
}
EOF
exit 1
;;
esac
