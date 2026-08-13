#!/bin/bash
# =============================================================
# DSM Session Manager
#
# Arquivo:
#   /opt/dsm/security/session_manager.sh
#
# DSM Version:
#   1.2.0
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

SESSIONS_DB="$DSM_ROOT/security/sessions.db"

SESSION_TIMEOUT=3600   # 1 hora



# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------

init()
{
    mkdir -p "$(dirname "$SESSIONS_DB")"

    if [ ! -f "$SESSIONS_DB" ]; then
        echo '{ "sessions":[] }' > "$SESSIONS_DB"
    fi
}



# -------------------------------------------------------------
# Timestamp
# -------------------------------------------------------------

now()
{
    date +%s
}



# -------------------------------------------------------------
# Gerar Session ID
# -------------------------------------------------------------

generate_session_id()
{
    if command -v uuidgen >/dev/null; then
        uuidgen
    else
        openssl rand -hex 32
    fi
}



# -------------------------------------------------------------
# Criar sessão
# -------------------------------------------------------------

create()
{
    local USER="$1"
    local IP="$2"

    init

    local SID
    SID=$(generate_session_id)

    local CREATED
    CREATED=$(now)

    local EXPIRES
    EXPIRES=$((CREATED+SESSION_TIMEOUT))

    TMP=$(mktemp)

    jq \
        --arg sid "$SID" \
        --arg user "$USER" \
        --arg ip "$IP" \
        --argjson created "$CREATED" \
        --argjson expires "$EXPIRES" \
'
.sessions += [
{
    session_id:$sid,
    username:$user,
    ip:$ip,
    created:$created,
    expires:$expires,
    last_activity:$created
}
]
' \
"$SESSIONS_DB" > "$TMP"

    mv "$TMP" "$SESSIONS_DB"

    echo "$SID"
}



# -------------------------------------------------------------
# Validar sessão
# -------------------------------------------------------------

validate()
{
    local SID="$1"

    init

    local CURRENT
    CURRENT=$(now)

    jq -e \
        --arg sid "$SID" \
        --argjson now "$CURRENT" \
'
.sessions[]
| select(
      .session_id==$sid
      and
      .expires > $now
)
' \
"$SESSIONS_DB" >/dev/null
}



# -------------------------------------------------------------
# Renovar atividade
# -------------------------------------------------------------

touch_session()
{
    local SID="$1"

    local CURRENT
    CURRENT=$(now)

    local NEW_EXPIRE
    NEW_EXPIRE=$((CURRENT+SESSION_TIMEOUT))

    TMP=$(mktemp)

    jq \
      --arg sid "$SID" \
      --argjson now "$CURRENT" \
      --argjson exp "$NEW_EXPIRE" '
.sessions |= map(
    if .session_id==$sid then
        .last_activity=$now
      | .expires=$exp
    else .
    end
)
' "$SESSIONS_DB" > "$TMP"

    mv "$TMP" "$SESSIONS_DB"
}



# -------------------------------------------------------------
# Obter usuário
# -------------------------------------------------------------

username()
{
    local SID="$1"

    jq -r \
      --arg sid "$SID" \
'
.sessions[]
| select(.session_id==$sid)
| .username
' \
"$SESSIONS_DB"
}



# -------------------------------------------------------------
# Remover sessão
# -------------------------------------------------------------

destroy()
{
    local SID="$1"

    TMP=$(mktemp)

    jq \
      --arg sid "$SID" '
.sessions |= map(
    select(.session_id != $sid)
)
' \
"$SESSIONS_DB" > "$TMP"

    mv "$TMP" "$SESSIONS_DB"
}



# -------------------------------------------------------------
# Limpar expiradas
# -------------------------------------------------------------

cleanup()
{
    local CURRENT
    CURRENT=$(now)

    TMP=$(mktemp)

    jq \
      --argjson now "$CURRENT" '
.sessions |= map(
    select(.expires > $now)
)
' \
"$SESSIONS_DB" > "$TMP"

    mv "$TMP" "$SESSIONS_DB"
}



# -------------------------------------------------------------
# Informações
# -------------------------------------------------------------

info()
{
    local SID="$1"

    jq \
      --arg sid "$SID" '
.sessions[]
| select(.session_id==$sid)
' \
"$SESSIONS_DB"
}



# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in

create)

create "$2" "$3"

;;

validate)

validate "$2"
exit $?

;;

touch)

touch_session "$2"

;;

destroy)

destroy "$2"

;;

cleanup)

cleanup

;;

user)

username "$2"

;;

info)

info "$2"

;;

*)

cat <<EOF

DSM Session Manager

Uso:

session_manager.sh create usuario ip

session_manager.sh validate session_id

session_manager.sh touch session_id

session_manager.sh destroy session_id

session_manager.sh cleanup

session_manager.sh user session_id

session_manager.sh info session_id

EOF

;;

esac