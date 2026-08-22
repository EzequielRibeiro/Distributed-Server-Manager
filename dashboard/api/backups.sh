#!/usr/bin/env bash
# =============================================================
# Capivara DSM Dashboard API
#
# backups.sh
#
# Retorna o estado agregado e o histórico recente dos backups
# do Controller em JSON, preservando os campos legados usados
# pelo Dashboard (total, last_backup, last_date e total_size).
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
BACKUP_DIR="${DSM_BACKUP_DIR:-/opt/dsm-backup}"
BACKUP_HISTORY_LIMIT="${DSM_BACKUP_HISTORY_LIMIT:-20}"

export DSM_ROOT BACKUP_DIR BACKUP_HISTORY_LIMIT

python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

backup_dir = Path(os.environ["BACKUP_DIR"]).expanduser()

try:
    history_limit = max(1, min(int(os.environ.get("BACKUP_HISTORY_LIMIT", "20")), 100))
except ValueError:
    history_limit = 20


def human_size(size_bytes):
    value = float(size_bytes)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size_bytes} B"


def empty_payload(status):
    return {
        "total": 0,
        "last_backup": "",
        "last_date": "",
        "total_size": "0 B",
        "total_size_bytes": 0,
        "status": status,
        "history": [],
    }


if not backup_dir.is_dir():
    print(json.dumps(empty_payload("NOT_FOUND"), ensure_ascii=False))
    raise SystemExit(0)

backups = []
for path in backup_dir.glob("*.tar.gz"):
    if not path.is_file():
        continue
    try:
        stat = path.stat()
    except OSError:
        continue
    backups.append((path, stat))

if not backups:
    print(json.dumps(empty_payload("EMPTY"), ensure_ascii=False))
    raise SystemExit(0)

# Arquivos mais recentes primeiro. O mtime é usado em vez do nome do
# arquivo para que o histórico continue correto com esquemas de nomes
# diferentes ou backups importados.
backups.sort(key=lambda item: item[1].st_mtime, reverse=True)

total_size_bytes = sum(stat.st_size for _, stat in backups)
latest_path, latest_stat = backups[0]
latest_dt = datetime.fromtimestamp(latest_stat.st_mtime, tz=timezone.utc)

history = []
for path, stat in backups[:history_limit]:
    dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    history.append(
        {
            "name": path.name,
            "date": dt.isoformat().replace("+00:00", "Z"),
            "size": human_size(stat.st_size),
            "size_bytes": stat.st_size,
        }
    )

payload = {
    "total": len(backups),
    "last_backup": latest_path.name,
    # Compatibilidade com o Dashboard atual, que mostra last_date como texto.
    "last_date": latest_dt.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
    "last_date_iso": latest_dt.isoformat().replace("+00:00", "Z"),
    "total_size": human_size(total_size_bytes),
    "total_size_bytes": total_size_bytes,
    "status": "OK",
    "history": history,
}

print(json.dumps(payload, ensure_ascii=False))
PY
