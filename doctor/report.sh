#!/bin/bash
# =============================================================
# doctor/report.sh - MÓDULO 05 (DOCTOR)
# Salva o relatório do último diagnóstico em disco (texto e JSON)
# =============================================================

LOG_MODULE="doctor"

DOCTOR_REPORT_DIR="${DSM_ROOT}/cache/doctor"

report_save() {
    mkdir -p "$DOCTOR_REPORT_DIR"
    local ts
    ts="$(date '+%Y%m%d_%H%M%S')"
    local txt_path="$DOCTOR_REPORT_DIR/report_${ts}.txt"
    local json_path="$DOCTOR_REPORT_DIR/latest.json"

    {
        echo "DSM Doctor Report - $(date '+%Y-%m-%d %H:%M:%S')"
        echo "Score: $DOCTOR_SCORE / $DOCTOR_MAX"
        echo ""
        for entry in "${DOCTOR_REPORT[@]}"; do
            IFS='|' read -r label ok detail <<< "$entry"
            echo "[$([ "$ok" -eq 0 ] && echo OK || echo FALHA)] $label: $detail"
        done
    } > "$txt_path"

    # JSON para a dashboard
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -Iseconds)\","
        echo "  \"score\": $DOCTOR_SCORE,"
        echo "  \"max\": $DOCTOR_MAX,"
        echo "  \"checks\": ["
        local first=1
        for entry in "${DOCTOR_REPORT[@]}"; do
            IFS='|' read -r label ok detail <<< "$entry"
            [ "$first" -eq 0 ] && echo ","
            first=0
            local safe_detail
            safe_detail="$(echo "$detail" | sed 's/"/\\"/g')"
            printf '    {"label": "%s", "ok": %s, "detail": "%s"}' "$label" "$([ "$ok" -eq 0 ] && echo true || echo false)" "$safe_detail"
        done
        echo ""
        echo "  ]"
        echo "}"
    } > "$json_path"

    log_debug "Relatório salvo em $txt_path"
    echo "$txt_path"
}

report_latest_json() {
    local json_path="$DOCTOR_REPORT_DIR/latest.json"
    [ -f "$json_path" ] && cat "$json_path" || echo "{}"
}

report_history() {
    ls -1t "$DOCTOR_REPORT_DIR"/report_*.txt 2>/dev/null | head -n "${1:-10}"
}
