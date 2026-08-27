#!/usr/bin/env bash
# =============================================================
# monitor/resources.sh - MÓDULO 04 (MONITOR)
# Coleta métricas do processo e do host.
# Fonte oficial do processo: server_pid()
# =============================================================

if [ -z "${DSM_ROOT:-}" ]; then
    DSM_ROOT="/opt/dsm"
fi

source "$DSM_ROOT/server/server.sh"

LOG_MODULE="monitor"
HEALTH_DISK_WARN_PCT="${HEALTH_DISK_WARN_PCT:-15}"
HEALTH_RAM_WARN_PCT="${HEALTH_RAM_WARN_PCT:-10}"

resources_process_cpu()
{
    local pid
    pid="$(server_pid)"
    [ -z "$pid" ] && { echo 0; return; }
    ps -p "$pid" -o %cpu= 2>/dev/null | xargs || echo "0"
}

resources_process_ram_mb()
{
    local pid
    pid="$(server_pid)"
    [ -z "$pid" ] && { echo 0; return; }
    ps -p "$pid" -o rss= 2>/dev/null | awk '{printf "%.1f", $1/1024}' || echo "0"
}

resources_disk_target()
{
    if [[ -n "${DSM_DATA_DIR:-}" && -e "${DSM_DATA_DIR}" ]]
    then
        printf '%s\n' "${DSM_DATA_DIR}"
    elif [[ -e "${DSM_ROOT}" ]]
    then
        printf '%s\n' "${DSM_ROOT}"
    else
        printf '/\n'
    fi
}

resources_disk_free_pct()
{
    local result
    result="$(df "$(resources_disk_target)" 2>/dev/null | awk 'NR==2{gsub("%","",$5); print 100-$5}')"
    echo "${result:-0}"
}

resources_disk_free_human()
{
    local result
    result="$(df -h "$(resources_disk_target)" 2>/dev/null | awk 'NR==2{print $4}')"
    echo "${result:--}"
}

resources_ram_free_pct()
{
    local result
    result="$(free 2>/dev/null | awk '/Mem:/{printf "%.0f",$7/$2*100}')"
    echo "${result:-0}"
}

resources_network_iface()
{
    ip route 2>/dev/null | awk '/^default/{print $5; exit}'
}

resources_network_rx_tx_mb()
{
    local iface
    iface="$(resources_network_iface)"
    [ -z "$iface" ] && { echo "0 0"; return; }
    awk -v ifc="$iface:" '$0 ~ ifc {gsub(ifc,""); print int($1/1024/1024), int($9/1024/1024)}' /proc/net/dev 2>/dev/null || echo "0 0"
}

resources_load_average()
{
    awk '{print $1,$2,$3}' /proc/loadavg 2>/dev/null || echo "0 0 0"
}

resources_host_uptime()
{
    uptime -p 2>/dev/null || echo "unknown"
}

resources_temperature()
{
    if command -v sensors >/dev/null 2>&1
    then
        sensors 2>/dev/null | grep -m1 -E "Package id|Core 0|CPU Temperature" | awk '{print $4}'
        return
    fi
    echo "N/A"
}

resources_json()
{
    local rxtx cpu ram disk_pct disk_human host_ram load uptime_host temp
    rxtx="$(resources_network_rx_tx_mb)"
    cpu="$(resources_process_cpu)"
    ram="$(resources_process_ram_mb)"
    disk_pct="$(resources_disk_free_pct)"
    disk_human="$(resources_disk_free_human)"
    host_ram="$(resources_ram_free_pct)"
    load="$(resources_load_average)"
    uptime_host="$(resources_host_uptime)"
    temp="$(resources_temperature)"

    cat <<EOF
{
  "cpu_pct": "$cpu",
  "ram_mb": "$ram",
  "disk_free_pct": "$disk_pct",
  "disk_free_human": "$disk_human",
  "host_ram_free_pct": "$host_ram",
  "network_rx_mb": "$(echo "$rxtx" | awk '{print $1}')",
  "network_tx_mb": "$(echo "$rxtx" | awk '{print $2}')",
  "load_average": {
      "1m": "$(echo "$load" | awk '{print $1}')",
      "5m": "$(echo "$load" | awk '{print $2}')",
      "15m": "$(echo "$load" | awk '{print $3}')"
  },
  "host_uptime": "$uptime_host",
  "temperature": "$temp"
}
EOF
}
