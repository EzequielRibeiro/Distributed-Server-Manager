#!/bin/bash
# ============================================================
# DSM Authentication API
# Arquivo:
#   /opt/dsm/api/auth_api.sh
# DSM Version:
#   1.2.0
# ============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

AUTH="$DSM_ROOT/security/auth_manager.sh"
SESSION="$DSM_ROOT/security/session_manager.sh"
CSRF="$DSM_ROOT/security/csrf.sh"
AUDIT="$DSM_ROOT/security/audit.sh"

CONTENT_TYPE="application/json"

# ------------------------------------------------------------
# Resposta JSON
# ------------------------------------------------------------
json() {
    local STATUS="$1"
    local BODY="$2"

    echo "Content-Type: $CONTENT_TYPE"
    echo
    echo "$BODY"

    exit "$STATUS"
}

# ------------------------------------------------------------
# COOKIE
# ------------------------------------------------------------
send_cookie() {
    local SID="$1"
    echo "Set-Cookie: DSM_SESSION=$SID; Path=/; HttpOnly; SameSite=Strict; Max-Age=3600"
}

# ------------------------------------------------------------
# LOGIN
# ------------------------------------------------------------
login() {
    local USER="$1"
    local PASSWORD="$2"
    local IP="$3"

    "$AUTH" auth "$USER" "$PASSWORD"
    RESULT=$?
    if [ "$RESULT" -ne 0 ]
    then
        "$AUDIT" login_failed "$USER" "$IP"
        json 1 \
'{
"success":false,
"message":"Usuário ou senha inválidos"
}'
    fi

    SID=$("$SESSION" create "$USER" "$IP")
    TOKEN=$("$CSRF" generate "$SID")
    "$AUDIT" login "$USER" "$IP"
    send_cookie "$SID"

    json 0 \
"{
\"success\":true,
\"user\":\"$USER\",
\"session\":\"$SID\",
\"csrf\":\"$TOKEN\"
}"
}

# ------------------------------------------------------------
# LOGOUT
# ------------------------------------------------------------
logout() {
    local SID="$1"
    local IP="$2"

    USER=$("$SESSION" user "$SID")
    "$SESSION" destroy "$SID"
    "$AUDIT" logout "$USER" "$IP"
    echo "Set-Cookie: DSM_SESSION=deleted; Max-Age=0; Path=/"

    json 0 \
'{
"success":true
}'
}

# ------------------------------------------------------------
# VALIDAR
# ------------------------------------------------------------
validate() {
    local SID="$1"
    if "$SESSION" validate "$SID"
    then
        USER=$("$SESSION" user "$SID")
        json 0 \
"{
\"authenticated\":true,
\"user\":\"$USER\"
}"
    fi
    json 1 \
'{
"authenticated":false
}'
}

# ------------------------------------------------------------
# RENOVAR
# ------------------------------------------------------------
refresh() {
    local SID="$1"
    "$SESSION" touch "$SID"
    TOKEN=$("$CSRF" generate "$SID")
    json 0 \
"{
\"success\":true,
\"csrf\":\"$TOKEN\"
}"
}

# ------------------------------------------------------------
# Entrada principal
# ------------------------------------------------------------
ACTION="$1"

case "$ACTION" in
login)
    login "$2" "$3" "$4"
;;
logout)
    logout "$2" "$3"
;;
validate)
    validate "$2"
;;
refresh)
    refresh "$2"
;;
*)
    json 1 \
'{
"success":false,
"message":"API inválida"
}'
;;
esac
