#!/bin/bash
# =============================================================
# monitor/metrics/network.sh - DSM Metrics Engine v1.1.0
# Coleta:
#   - Interface de rede ativa
#   - Bytes recebidos (RX)
#   - Bytes enviados (TX)
#   - MB recebidos
#   - MB enviados
#   - Pacotes RX/TX
# =============================================================

LOG_MODULE="metrics-network"

# =============================================================
# Interface principal
# Obtém interface usada pela rota padrão
# =============================================================
metrics_network_interface()
{
    ip route 2>/dev/null |
    awk '/default/ {
        print $5;
        exit
    }'
}

# =============================================================
# Dados brutos da interface
# /proc/net/dev
# RX: bytes packets errors drop
# TX: bytes packets errors drop
# =============================================================
metrics_network_raw()
{
    local iface
    iface="$(metrics_network_interface)"

    if [ -z "$iface" ]; then
        echo "0 0 0 0"
        return
    fi

    awk -v dev="$iface:" '
    $1 == dev {
        print $2,
             $3,
             $10,
             $11
    }' /proc/net/dev 2>/dev/null
}

# =============================================================
# Bytes recebidos
# =============================================================
metrics_network_rx_bytes()
{
    metrics_network_raw |
    awk '{print $1}'
}

# =============================================================
# Bytes enviados
# =============================================================
metrics_network_tx_bytes()
{
    metrics_network_raw |
    awk '{print $3}'
}

# =============================================================
# RX em MB
# =============================================================
metrics_network_rx_mb()
{
    local bytes
    bytes="$(metrics_network_rx_bytes)"

    echo "${bytes:-0}" |
    awk '
    {
        printf "%.2f",
        $1/1024/1024
    }'
}

# =============================================================
# TX em MB
# =============================================================
metrics_network_tx_mb()
{
    local bytes
    bytes="$(metrics_network_tx_bytes)"

    echo "${bytes:-0}" |
    awk '
    {
        printf "%.2f",
        $1/1024/1024
    }'
}

# =============================================================
# Pacotes recebidos
# =============================================================
metrics_network_rx_packets()
{
    metrics_network_raw |
    awk '{print $2}'
}

# =============================================================
# Pacotes enviados
# =============================================================
metrics_network_tx_packets()
{
    metrics_network_raw |
    awk '{print $4}'
}

# =============================================================
# JSON do módulo Network
# =============================================================
metrics_network_json()
{
cat <<EOF
{
    "interface": "$(metrics_network_interface)",
    "rx_mb": "$(metrics_network_rx_mb)",
    "tx_mb": "$(metrics_network_tx_mb)",
    "rx_packets": "$(metrics_network_rx_packets)",
    "tx_packets": "$(metrics_network_tx_packets)"
}
EOF
}
