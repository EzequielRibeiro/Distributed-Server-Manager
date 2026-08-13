#!/bin/bash
# =============================================================
# DSM Permission Manager
#
# Arquivo:
#   /opt/dsm/security/permissions.sh
#
# DSM Version:
#   1.2.0
# =============================================================

#
# Lista de permissões por perfil
#

declare -A ROLE_PERMISSIONS

ROLE_PERMISSIONS[admin]="
dashboard.view
dashboard.metrics
dashboard.logs
dashboard.alerts

server.start
server.stop
server.restart

mods.update

backup.create
backup.restore

steam.update

config.read
config.write

discord.test

users.manage

alerts.ack
"

ROLE_PERMISSIONS[operator]="
dashboard.view
dashboard.metrics
dashboard.logs
dashboard.alerts

discord.test

alerts.ack
"



# -------------------------------------------------------------
# Verificar permissão
# -------------------------------------------------------------

has_permission()
{
    local ROLE="$1"
    local PERMISSION="$2"

    echo "${ROLE_PERMISSIONS[$ROLE]}" |
    grep -Fxq "$PERMISSION"
}



# -------------------------------------------------------------
# Listar permissões
# -------------------------------------------------------------

list_permissions()
{
    local ROLE="$1"

    echo "${ROLE_PERMISSIONS[$ROLE]}"
}



# -------------------------------------------------------------
# Verificar API
# -------------------------------------------------------------

api_permission()
{
    local ROLE="$1"
    local API="$2"

    case "$API" in

restart)

has_permission "$ROLE" server.restart

;;

stop)

has_permission "$ROLE" server.stop

;;

start)

has_permission "$ROLE" server.start

;;

backup)

has_permission "$ROLE" backup.create

;;

restore)

has_permission "$ROLE" backup.restore

;;

steam_update)

has_permission "$ROLE" steam.update

;;

mods_update)

has_permission "$ROLE" mods.update

;;

config)

has_permission "$ROLE" config.write

;;

discord_test)

has_permission "$ROLE" discord.test

;;

dashboard)

has_permission "$ROLE" dashboard.view

;;

*)

return 1

;;

esac
}



# -------------------------------------------------------------
# Dashboard
# -------------------------------------------------------------

dashboard_permission()
{
    local ROLE="$1"

    has_permission "$ROLE" dashboard.view
}



# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in

check)

has_permission "$2" "$3"
exit $?

;;

list)

list_permissions "$2"

;;

api)

api_permission "$2" "$3"
exit $?

;;

dashboard)

dashboard_permission "$2"
exit $?

;;

*)

cat <<EOF

DSM Permission Manager

Uso:

permissions.sh check ROLE PERMISSION

permissions.sh list ROLE

permissions.sh api ROLE API

permissions.sh dashboard ROLE

EOF

;;

esac