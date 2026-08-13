#!/bin/bash
# =============================================================
# DSM CSRF Protection
#
# Arquivo:
#   /opt/dsm/security/csrf.sh
#
# DSM Version:
#   1.2.0
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

CSRF_DB="$DSM_ROOT/security/csrf.db"

TOKEN_TTL=3600



# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------

init()
{
    mkdir -p "$(dirname "$CSRF_DB")"

    if [ ! -f "$CSRF_DB" ]; then
        echo '{ "tokens":[] }' > "$CSRF_DB"
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
# Gerar Token
# -------------------------------------------------------------

generate_token()
{
    openssl rand -hex 32
}



# -------------------------------------------------------------
# Criar Token
# -------------------------------------------------------------

generate()
{
    local SESSION="$1"

    init

    local TOKEN
    TOKEN=$(generate_token)

    local CREATED
    CREATED=$(now)

    local EXPIRES
    EXPIRES=$((CREATED+TOKEN_TTL))

    local TMP
    TMP=$(mktemp)

    jq \
      --arg session "$SESSION" \
      --arg token "$TOKEN" \
      --argjson created "$CREATED" \
      --argjson expires "$EXPIRES" '
.tokens += [
{
    session:$session,
    token:$token,
    created:$created,
    expires:$expires
}
]
' \
"$CSRF_DB" > "$TMP"

    mv "$TMP" "$CSRF_DB"

    echo "$TOKEN"
}



# -------------------------------------------------------------
# Validar Token
# -------------------------------------------------------------

validate()
{
    local SESSION="$1"
    local TOKEN="$2"

    init

    local CURRENT
    CURRENT=$(now)

    jq -e \
      --arg session "$SESSION" \
      --arg token "$TOKEN" \
      --argjson now "$CURRENT" '
.tokens[]
| select(
    .session==$session
    and
    .token==$token
    and
    .expires>$now
)
' \
"$CSRF_DB" >/dev/null
}



# -------------------------------------------------------------
# Revogar Token
# -------------------------------------------------------------

revoke()
{
    local TOKEN="$1"

    local TMP
    TMP=$(mktemp)

    jq \
      --arg token "$TOKEN" '
.tokens |= map(
    select(.token != $token)
)
' \
"$CSRF_DB" > "$TMP"

    mv "$TMP" "$CSRF_DB"
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
.tokens |= map(
    select(.expires > $now)
)
' \
"$CSRF_DB" > "$TMP"

    mv "$TMP" "$CSRF_DB"
}



# -------------------------------------------------------------
# Informações
# -------------------------------------------------------------

info()
{
    local TOKEN="$1"

    jq \
      --arg token "$TOKEN" '
.tokens[]
| select(.token==$token)
' \
"$CSRF_DB"
}



# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in

generate)

generate "$2"

;;

validate)

validate "$2" "$3"
exit $?

;;

revoke)

revoke "$2"

;;

cleanup)

cleanup

;;

info)

info "$2"

;;

*)

cat <<EOF

DSM CSRF Protection

Uso:

csrf.sh generate SESSION_ID

csrf.sh validate SESSION_ID TOKEN

csrf.sh revoke TOKEN

csrf.sh cleanup

csrf.sh info TOKEN

EOF

;;

esac