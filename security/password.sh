#!/bin/bash
# =============================================================
# DSM Password Manager
#
# Arquivo:
#   /opt/dsm/security/password.sh
#
# DSM Version:
#   1.2.0
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

USERS_DB="$DSM_ROOT/config/users.db"

DEFAULT_ITERATIONS=200000



# -------------------------------------------------------------
# Gerar Salt
# -------------------------------------------------------------

generate_salt()
{
    openssl rand -hex 16
}



# -------------------------------------------------------------
# Gerar Hash PBKDF2-SHA256
# -------------------------------------------------------------

generate_hash()
{
    local PASSWORD="$1"
    local SALT="$2"
    local ITERATIONS="${3:-$DEFAULT_ITERATIONS}"

    printf "%s" "$PASSWORD" |
    openssl kdf \
        -keylen 32 \
        -kdfopt digest:SHA256 \
        -kdfopt pass:"$PASSWORD" \
        -kdfopt salt:"$SALT" \
        -kdfopt iter:"$ITERATIONS" \
        PBKDF2 2>/dev/null |
    xxd -p -c 256
}



# -------------------------------------------------------------
# Obter campo do usuário
# -------------------------------------------------------------

get_field()
{
    local USER="$1"
    local FIELD="$2"

    jq -r \
      --arg u "$USER" \
      --arg f "$FIELD" \
      '.users[]
      | select(.username==$u)
      | .password[$f]' \
      "$USERS_DB"
}



# -------------------------------------------------------------
# Verificar senha
# -------------------------------------------------------------

verify()
{
    local USER="$1"
    local PASSWORD="$2"

    local SALT
    local HASH
    local ITER

    SALT=$(get_field "$USER" salt)
    HASH=$(get_field "$USER" hash)
    ITER=$(get_field "$USER" iterations)

    [ "$SALT" = "null" ] && return 1
    [ "$HASH" = "null" ] && return 1

    local TEST_HASH

    TEST_HASH=$(generate_hash "$PASSWORD" "$SALT" "$ITER")

    [ "$TEST_HASH" = "$HASH" ]
}



# -------------------------------------------------------------
# Política mínima
# -------------------------------------------------------------

validate_policy()
{
    local PASSWORD="$1"

    [ ${#PASSWORD} -lt 8 ] && return 1

    echo "$PASSWORD" | grep -q '[A-Z]' || return 2
    echo "$PASSWORD" | grep -q '[a-z]' || return 3
    echo "$PASSWORD" | grep -q '[0-9]' || return 4

    return 0
}



# -------------------------------------------------------------
# Atualizar senha
# -------------------------------------------------------------

set_password()
{
    local USER="$1"
    local PASSWORD="$2"

    validate_policy "$PASSWORD"
    local POLICY_RESULT=$?

    if [ "$POLICY_RESULT" -ne 0 ]; then
        return "$POLICY_RESULT"
    fi

    local SALT
    SALT=$(generate_salt)

    local HASH
    HASH=$(generate_hash "$PASSWORD" "$SALT")

    local TMP
    TMP=$(mktemp)

    jq \
      --arg u "$USER" \
      --arg s "$SALT" \
      --arg h "$HASH" \
      --arg d "$(date -Iseconds)" \
      --argjson i "$DEFAULT_ITERATIONS" '
      .users |= map(
        if .username==$u then
            .password.salt=$s
          | .password.hash=$h
          | .password.iterations=$i
          | .password_changed_at=$d
        else .
        end
      )
      ' "$USERS_DB" > "$TMP"

    mv "$TMP" "$USERS_DB"

    return 0
}



# -------------------------------------------------------------
# Inicializar administrador
# -------------------------------------------------------------

initialize_admin()
{
    local PASSWORD="$1"

    set_password admin "$PASSWORD"
}



# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "$1" in

verify)

verify "$2" "$3"
exit $?

;;

set)

set_password "$2" "$3"
exit $?

;;

init)

initialize_admin "$2"
exit $?

;;

policy)

validate_policy "$2"
exit $?

;;

*)

cat <<EOF

DSM Password Manager

Uso:

password.sh verify usuario senha

password.sh set usuario senha

password.sh init senha_admin

password.sh policy senha

EOF

;;

esac