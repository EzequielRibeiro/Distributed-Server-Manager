#!/usr/bin/env bash

set -Eeuo pipefail

source /opt/dsm/core/platform.sh

load_game

DSM_ROOT="/opt/dsm"

GAME_ROOT="${INSTALL_DIR}"

PROFILE_DIR="${GAME_ROOT}/${PROFILE_PATH}"

MODS_DIR="${GAME_ROOT}/${MOD_PATH}"

BACKUP_DIR="/opt/dsm-backup"

LOG_DIR="${DSM_ROOT}/logs"

STATE_DIR="${DSM_ROOT}/runtime"

CONFIG_DIR="${DSM_ROOT}/config"

WORK_DIR="${DSM_ROOT}/work"