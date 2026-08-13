#!/bin/bash
# =============================================================
# core/lock.sh - MÓDULO 01 (CORE)
#
# Sistema de travas do DSM.
#
# Responsável por:
# - impedir execuções concorrentes
# - detectar travas órfãs
# - registrar informações da trava
#
# Utilizado por:
# - backup
# - update
# - scheduler
# - monitor
# - mods
#
# =============================================================

LOG_MODULE="core"
DSM_LOCK_DIR="${DSM_ROOT}/tmp/locks"

# =============================================================
# Caminho da trava
# =============================================================
_lock_path()
{
    printf "%s/%s.lock" "$DSM_LOCK_DIR" "$1"
}

# =============================================================
# Adquire trava
#
# Retorno:
#   0 = sucesso
#   1 = ocupado
#
# =============================================================
lock_acquire()
{
    local name="$1"
    local path

    path="$(_lock_path "$name")"
    mkdir -p "$DSM_LOCK_DIR"

    if mkdir "$path" 2>/dev/null
    then
        echo "$$" > "$path/pid"
        date --iso-8601=seconds > "$path/since"
        hostname > "$path/host"
        return 0
    fi

    local owner_pid
    owner_pid="$(cat "$path/pid" 2>/dev/null)"

    if [ -n "$owner_pid" ] &&
       kill -0 "$owner_pid" 2>/dev/null
    then
        return 1
    fi

    log_warn "Removendo trava órfã: $name"
    rm -rf "$path"
    mkdir "$path"

    echo "$$" > "$path/pid"
    date --iso-8601=seconds > "$path/since"
    hostname > "$path/host"

    return 0
}

# =============================================================
# Libera trava
# =============================================================
lock_release()
{
    rm -rf "$(_lock_path "$1")"
}

# =============================================================
# Verifica trava ativa
# =============================================================
lock_is_locked()
{
    local path
    local pid

    path="$(_lock_path "$1")"
    [ -d "$path" ] || return 1
    pid="$(cat "$path/pid" 2>/dev/null)"

    [ -n "$pid" ] &&
    kill -0 "$pid" 2>/dev/null
}

# =============================================================
# Informações da trava
#
# Uso:
#   lock_info backup
#
# =============================================================
lock_info()
{
    local path

    path="$(_lock_path "$1")"
    [ -d "$path" ] || return 1

    cat <<EOF
PID:     $(cat "$path/pid" 2>/dev/null)
Desde:   $(cat "$path/since" 2>/dev/null)
Host:    $(cat "$path/host" 2>/dev/null)
EOF
}

# =============================================================
# Executa protegido por trava
#
# Uso:
#   lock_run backup backup_run
#
# =============================================================
lock_run()
{
    local name="$1"
    shift

    if ! lock_acquire "$name"
    then
        log_warn "Operação '$name' já está em execução."
        return 1
    fi

    "$@"
    local rc=$?
    lock_release "$name"
    return "$rc"
}
