#!/usr/bin/env bash
set -Eeuo pipefail

SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

legacy_units=(
  dsm-monitor.service
  dsm-scheduler.service
  dsm-automation-worker.service
)

required_units=(
  dsm-dashboard-worker.service
  dsm-alert-engine.service
)

for unit in "${legacy_units[@]}"; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  rm -f -- "${SYSTEMD_DIR}/${unit}"
done

systemctl daemon-reload

for unit in "${required_units[@]}"; do
  if systemctl cat "$unit" >/dev/null 2>&1; then
    systemctl enable "$unit" >/dev/null 2>&1 || true
  fi
done
