#!/usr/bin/env bash
# =============================================================
# DSM Universal Event Manager
#
# Commit 14A
#
# Compatibilidade com módulos antigos
# Agora integrado ao Event Core
#
# Modelo:
#
# SERVER / GAME / INSTANCE
#
# =============================================================


set -Eeuo pipefail



DSM_ROOT="${DSM_ROOT:-/opt/dsm}"



# =============================================================
# Event Core
# =============================================================

source "${DSM_ROOT}/core/events.sh"



# =============================================================
# Argumentos
# =============================================================

CATEGORY="${1:-system}"

TYPE="${2:-SYSTEM_EVENT}"

MESSAGE="${3:-DSM event}"



# =============================================================
# Resource Identity opcional
#
# Futuro:
#
# event_manager.sh \
# server \
# SERVER_START \
# "Servidor iniciado" \
# server01 \
# dayz \
# survival01
#
# =============================================================

SERVER="${4:-unknown}"

GAME="${5:-unknown}"

INSTANCE="${6:-unknown}"



# =============================================================
# Validação Resource Identity
#
# Garante identidade mínima:
#
# SERVER / GAME / INSTANCE
#
# Evita eventos sem recurso definido
#
# =============================================================

if [ -z "$SERVER" ]
then
    SERVER="unknown"
fi


if [ -z "$GAME" ]
then
    GAME="unknown"
fi


if [ -z "$INSTANCE" ]
then
    INSTANCE="unknown"
fi



# =============================================================
# Dispatcher
# =============================================================

case "$CATEGORY" in


server)

    event_info \
    "$TYPE" \
    server \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;



player)

    event_info \
    "$TYPE" \
    player \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;



combat)

    event_info \
    "$TYPE" \
    combat \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;



admin)

    event_info \
    "$TYPE" \
    audit \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;



backup)

    event_info \
    "$TYPE" \
    backup \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;



update)

    event_info \
    "$TYPE" \
    update \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;



mod)

    event_info \
    "$TYPE" \
    mod \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;



system|*)

    event_info \
    "$TYPE" \
    system \
    "$MESSAGE" \
    DSM \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"

;;

esac