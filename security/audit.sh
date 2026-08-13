#!/bin/bash
# =============================================================
# DSM Audit Manager
#
# Arquivo:
#   /opt/dsm/security/audit.sh
#
# DSM Version:
#   1.2.0
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

AUDIT_LOG="$DSM_ROOT/logs/audit.log"

mkdir -p "$(dirname "$AUDIT_LOG")"

EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"

# -------------------------------------------------------------
# Timestamp UTC
# -------------------------------------------------------------

timestamp()
{
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}



# -------------------------------------------------------------
# Escrever evento
# -------------------------------------------------------------

write()
{

    local USER="$1"
    local IP="$2"
    local ACTION="$3"
    local STATUS="$4"
    local DETAILS="$5"

    printf "%s | %s | %s | %s | %s | %s\n" \
        "$(timestamp)" \
        "$USER" \
        "$IP" \
        "$ACTION" \
        "$STATUS" \
        "$DETAILS" \
        >> "$AUDIT_LOG"

}

# -------------------------------------------------------------
# Enviar evento
# -------------------------------------------------------------

send_event()
{

TYPE="$1"
MESSAGE="$2"


if [ -x "$EVENT_MANAGER" ]

then


"$EVENT_MANAGER" \
admin \
"$TYPE" \
"$MESSAGE"


fi

}

# -------------------------------------------------------------
# Login
# -------------------------------------------------------------

login()
{
    write "$1" "$2" LOGIN SUCCESS "Dashboard Login"

    send_event \
    LOGIN \
    "Usuário $1 realizou login"
}



# -------------------------------------------------------------
# Logout
# -------------------------------------------------------------

logout()
{
    write "$1" "$2" LOGOUT SUCCESS "Dashboard Logout"
}



# -------------------------------------------------------------
# Reinício
# -------------------------------------------------------------

restart()
{
    write "$1" "$2" SERVER_RESTART SUCCESS "Servidor reiniciado"
}



# -------------------------------------------------------------
# Start
# -------------------------------------------------------------

start()
{
    write "$1" "$2" SERVER_START SUCCESS "Servidor iniciado"
}



# -------------------------------------------------------------
# Stop
# -------------------------------------------------------------

stop()
{
    write "$1" "$2" SERVER_STOP SUCCESS "Servidor parado"
}



# -------------------------------------------------------------
# Backup
# -------------------------------------------------------------

backup()
{
    write "$1" "$2" BACKUP SUCCESS "$3"
}



# -------------------------------------------------------------
# Restore
# -------------------------------------------------------------

restore()
{
    write "$1" "$2" RESTORE SUCCESS "$3"
}



# -------------------------------------------------------------
# Atualização Mods
# -------------------------------------------------------------

mods()
{
    write "$1" "$2" MODS_UPDATE SUCCESS "$3"
}



# -------------------------------------------------------------
# Steam Update
# -------------------------------------------------------------

steam()
{
    write "$1" "$2" STEAM_UPDATE SUCCESS "$3"
}



# -------------------------------------------------------------
# Configuração
# -------------------------------------------------------------

config()
{
    write "$1" "$2" CONFIG_UPDATE SUCCESS "$3"
}



# -------------------------------------------------------------
# Usuários
# -------------------------------------------------------------

user_action()
{
    write "$1" "$2" USER_MANAGEMENT SUCCESS "$3"
}



# -------------------------------------------------------------
# Discord
# -------------------------------------------------------------

discord()
{
    write "$1" "$2" DISCORD_TEST SUCCESS "$3"
}



# -------------------------------------------------------------
# Falha de Login
# -------------------------------------------------------------

login_failed()
{
    write "$1" "$2" LOGIN FAILED "Senha incorreta"

    send_event \
    LOGIN_FAILED \
    "Falha login usuário $1"
}



# -------------------------------------------------------------
# Permissão Negada
# -------------------------------------------------------------

permission_denied()
{
    write "$1" "$2" ACCESS_DENIED FAILED "$3"

    send_event \
    ACCESS_DENIED \
    "Permissão negada: $3"
}



# -------------------------------------------------------------
# Evento Crítico
# -------------------------------------------------------------

critical()
{
    write "$1" "$2" CRITICAL FAILED "$3"
}



# -------------------------------------------------------------
# Consulta
# -------------------------------------------------------------

tail_log()
{
    tail -n "${1:-50}" "$AUDIT_LOG"
}



# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in

login)

login "$2" "$3"

;;

logout)

logout "$2" "$3"

;;

restart)

restart "$2" "$3"

;;

start)

start "$2" "$3"

;;

stop)

stop "$2" "$3"

;;

backup)

backup "$2" "$3" "$4"

;;

restore)

restore "$2" "$3" "$4"

;;

mods)

mods "$2" "$3" "$4"

;;

steam)

steam "$2" "$3" "$4"

;;

config)

config "$2" "$3" "$4"

;;

user)

user_action "$2" "$3" "$4"

;;

discord)

discord "$2" "$3" "$4"

;;

login_failed)

login_failed "$2" "$3"

;;

permission)

permission_denied "$2" "$3" "$4"

;;

critical)

critical "$2" "$3" "$4"

;;

tail)

tail_log "$2"

;;

*)

cat <<EOF

DSM Audit Manager

Uso:

audit.sh login usuario ip

audit.sh logout usuario ip

audit.sh restart usuario ip

audit.sh start usuario ip

audit.sh stop usuario ip

audit.sh backup usuario ip descricao

audit.sh restore usuario ip descricao

audit.sh mods usuario ip descricao

audit.sh steam usuario ip descricao

audit.sh config usuario ip descricao

audit.sh user usuario ip descricao

audit.sh discord usuario ip descricao

audit.sh login_failed usuario ip

audit.sh permission usuario ip recurso

audit.sh critical usuario ip descricao

audit.sh tail [linhas]

EOF

;;

esac