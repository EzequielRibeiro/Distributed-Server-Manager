#!/bin/bash
# =============================================================
# DSM Lockout Manager
#
# Arquivo:
#   /opt/dsm/security/lockout.sh
#
# DSM Version:
#   1.2.0
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

LOCKOUT_DB="$DSM_ROOT/security/lockout.db"

MAX_ATTEMPTS=5

LOCKOUT_TIME=900



# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------

init()
{

    mkdir -p "$(dirname "$LOCKOUT_DB")"

    if [ ! -f "$LOCKOUT_DB" ]
    then
        echo '{ "users":[] }' > "$LOCKOUT_DB"
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
# Criar registro
# -------------------------------------------------------------

create_record()
{

    local USER="$1"

    local TMP
    TMP=$(mktemp)

    jq \
      --arg user "$USER" '
.users += [
{
    username:$user,
    attempts:0,
    locked_until:0,
    last_fail:0
}
]
' \
"$LOCKOUT_DB" > "$TMP"

    mv "$TMP" "$LOCKOUT_DB"

}



# -------------------------------------------------------------
# Garantir registro
# -------------------------------------------------------------

ensure_user()
{

    local USER="$1"

    jq -e \
      --arg user "$USER" '
.users[]
| select(.username==$user)
' \
"$LOCKOUT_DB" >/dev/null

    if [ $? -ne 0 ]
    then
        create_record "$USER"
    fi

}



# -------------------------------------------------------------
# Login incorreto
# -------------------------------------------------------------

fail()
{

    local USER="$1"

    init
    ensure_user "$USER"

    local CURRENT
    CURRENT=$(now)

    local TMP
    TMP=$(mktemp)

    jq \
      --arg user "$USER" \
      --argjson now "$CURRENT" \
      --argjson max "$MAX_ATTEMPTS" \
      --argjson block "$LOCKOUT_TIME" '
.users |= map(

if .username==$user then

    .attempts += 1
    | .last_fail=$now
    | if .attempts >= $max then
            .locked_until=($now+$block)
      else .
      end

else .

end

)
' \
"$LOCKOUT_DB" > "$TMP"

    mv "$TMP" "$LOCKOUT_DB"

}



# -------------------------------------------------------------
# Login correto
# -------------------------------------------------------------

success()
{

    local USER="$1"

    init

    local TMP
    TMP=$(mktemp)

    jq \
      --arg user "$USER" '
.users |= map(

if .username==$user then

    .attempts=0
    | .locked_until=0

else .

end

)
' \
"$LOCKOUT_DB" > "$TMP"

    mv "$TMP" "$LOCKOUT_DB"

}



# -------------------------------------------------------------
# Verificar bloqueio
# -------------------------------------------------------------

check()
{

    local USER="$1"

    init
    ensure_user "$USER"

    local CURRENT
    CURRENT=$(now)

    local LOCK

    LOCK=$(jq -r \
      --arg user "$USER" '
.users[]
| select(.username==$user)
| .locked_until
' \
"$LOCKOUT_DB")

    [ "$LOCK" -le "$CURRENT" ]

}



# -------------------------------------------------------------
# Informações
# -------------------------------------------------------------

info()
{

    local USER="$1"

    jq \
      --arg user "$USER" '
.users[]
| select(.username==$user)
' \
"$LOCKOUT_DB"

}



# -------------------------------------------------------------
# Limpeza
# -------------------------------------------------------------

cleanup()
{

    local CURRENT
    CURRENT=$(now)

    local TMP
    TMP=$(mktemp)

    jq \
      --argjson now "$CURRENT" '
.users |= map(

if .locked_until < $now then

    .locked_until=0

else .

end

)
' \
"$LOCKOUT_DB" > "$TMP"

    mv "$TMP" "$LOCKOUT_DB"

}



# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in

fail)

fail "$2"

;;

success)

success "$2"

;;

check)

check "$2"
exit $?

;;

cleanup)

cleanup

;;

info)

info "$2"

;;

*)

cat <<EOF

DSM Lockout Manager

Uso:

lockout.sh fail usuario

lockout.sh success usuario

lockout.sh check usuario

lockout.sh cleanup

lockout.sh info usuario

EOF

;;

esac