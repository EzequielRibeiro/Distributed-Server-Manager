#!/usr/bin/env bash

set -Eeuo pipefail

source /opt/dsm/core/platform.sh

load_game

game_start() {

    runtime_start
}

game_stop() {

    runtime_stop
}

game_restart() {

    runtime_restart
}

game_status() {

    runtime_status
}

game_pid() {

    runtime_pid
}

game_logs() {

    runtime_logs
}