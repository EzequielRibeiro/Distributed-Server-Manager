#!/bin/bash
# =============================================================
# monitor/metrics/temperature.sh - DSM Metrics Engine v1.1.0
# sudo apt install lm-sensors
# sudo sensors-detect
# Coleta:
#   - Temperatura CPU
#   - Temperatura por núcleo
#   - Sensores disponíveis
#   - Fallback thermal_zone
# =============================================================

LOG_MODULE="metrics-temperature"

# =============================================================
# Verifica disponibilidade do sensors
# =============================================================
metrics_temperature_has_sensors()
{
    command -v sensors >/dev/null 2>&1
}

# =============================================================
# Temperatura via lm-sensors
# Procura: Package id, Tctl, Core 0
# =============================================================
metrics_temperature_sensor_cpu()
{
    if ! metrics_temperature_has_sensors; then
        echo "0"
        return
    fi

    sensors 2>/dev/null |
    awk '
    /Package id 0:/ {
        gsub("\\+|°C","");
        print $4;
        exit
    }
    /Tctl:/ {
        gsub("\\+|°C","");
        print $2;
        exit
    }
    '
}

# =============================================================
# Temperatura média dos núcleos
# =============================================================
metrics_temperature_cpu_average()
{
    if ! metrics_temperature_has_sensors; then
        echo "0"
        return
    fi

    sensors 2>/dev/null |
    awk '
    /Core [0-9]+:/ {
        gsub("\\+|°C","");
        total += $3;
        count++;
    }
    END {
        if(count>0)
            printf "%.1f", total/count;
        else
            print 0;
    }'
}

# =============================================================
# Fallback: /sys/class/thermal
# =============================================================
metrics_temperature_thermal_zone()
{
    local temp
    temp=$(find /sys/class/thermal \
        -name "temp" \
        -type f \
        2>/dev/null |
        head -1)

    if [ -z "$temp" ]; then
        echo "0"
        return
    fi

    cat "$temp" |
    awk '
    {
        printf "%.1f",
        $1/1000
    }'
}

# =============================================================
# Temperatura principal
# Ordem: 1 - lm-sensors, 2 - thermal_zone, 3 - zero
# =============================================================
metrics_temperature_cpu()
{
    local value
    value="$(metrics_temperature_sensor_cpu)"

    if [ -n "$value" ] && [ "$value" != "0" ]; then
        echo "$value"
        return
    fi
    value="$(metrics_temperature_thermal_zone)"
    echo "${value:-0}"
}

# =============================================================
# Status do sensor
# =============================================================
metrics_temperature_available()
{
    if metrics_temperature_has_sensors; then
        echo "true"
        return
    fi

    if find /sys/class/thermal \
        -name temp \
        -type f \
        2>/dev/null |
        grep -q temp; then
        echo "true"
        return
    fi
    echo "false"
}

# =============================================================
# JSON Temperature
# =============================================================
metrics_temperature_json()
{
cat <<EOF
{
    "available": $(metrics_temperature_available),
    "cpu_celsius": "$(metrics_temperature_cpu)",
    "cpu_average_celsius": "$(metrics_temperature_cpu_average)"
}
EOF
}
