#!/bin/bash
# =============================================================
# DSM Security Middleware
#
# Arquivo:
#   /opt/dsm/security/middleware.sh
#
# DSM Version:
#   1.2.0
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

SESSION="$DSM_ROOT/security/session_manager.sh"
AUTH="$DSM_ROOT/security/auth_manager.sh"
PERMISSIONS="$DSM_ROOT/security/permissions.sh"
CSRF="$DSM_ROOT/security/csrf.sh"
AUDIT="$DSM_ROOT/security/audit.sh"



# -------------------------------------------------------------
# Resposta HTTP
# -------------------------------------------------------------

http_error()
{

    local CODE="$1"
    local MESSAGE="$2"

    echo "Status: $CODE"

    echo "Content-Type: application/json"

    echo

    printf \
'{"success":false,"error":"%s"}\n' \
"$MESSAGE"

    exit 1

}



# -------------------------------------------------------------
# Middleware Principal
# -------------------------------------------------------------

protect()
{

    local SESSION_ID="$1"

    local CSRF_TOKEN="$2"

    local ACTION="$3"

    local IP="$4"



    #
    # Sessão
    #

    if ! "$SESSION" validate "$SESSION_ID"
    then

        http_error 401 "Sessão inválida"

    fi



    #
    # Renovar timeout
    #

    "$SESSION" touch "$SESSION_ID"



    #
    # Usuário
    #

    USERNAME=$("$SESSION" user "$SESSION_ID")



    #
    # Perfil
    #

    ROLE=$("$AUTH" role "$USERNAME")



    #
    # Permissão
    #

    if ! "$PERMISSIONS" api "$ROLE" "$ACTION"
    then

        "$AUDIT" permission \
            "$USERNAME" \
            "$IP" \
            "$ACTION"

        http_error 403 "Permissão negada"

    fi



    #
    # CSRF
    #

    if ! "$CSRF" validate \
        "$SESSION_ID" \
        "$CSRF_TOKEN"
    then

        "$AUDIT" critical \
            "$USERNAME" \
            "$IP" \
            "CSRF inválido"

        http_error 403 "Token CSRF inválido"

    fi



    #
    # OK
    #

    export DSM_USER="$USERNAME"

    export DSM_ROLE="$ROLE"

    export DSM_SESSION="$SESSION_ID"

    export DSM_IP="$IP"

}



# -------------------------------------------------------------
# Utilizado pelas APIs
# -------------------------------------------------------------

require()
{

    protect \
        "$1" \
        "$2" \
        "$3" \
        "$4"

}



# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in

protect)

protect \
"$2" \
"$3" \
"$4" \
"$5"

;;

*)

cat <<EOF

DSM Middleware

Uso:

middleware.sh protect

SESSION_ID

CSRF_TOKEN

AÇÃO

IP

EOF

;;

esac