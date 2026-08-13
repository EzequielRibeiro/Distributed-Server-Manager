#!/bin/bash
# =============================================================
# DSM Authentication Manager
#
# Arquivo:
#   /opt/dsm/security/auth_manager.sh
#
# DSM Version:
#   1.2.0
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

USERS_DB="$DSM_ROOT/config/users.db"

PASSWORD="$DSM_ROOT/security/password.sh"

LOCKOUT="$DSM_ROOT/security/lockout.sh"

LOGGER="$DSM_ROOT/security/logger.sh"



# =============================================================
# Código de retorno
# =============================================================

AUTH_OK=0
AUTH_INVALID_USER=10
AUTH_INVALID_PASSWORD=11
AUTH_DISABLED=12
AUTH_LOCKED=13



# =============================================================
# Verificar existência do banco
# =============================================================

db_exists()
{

    [ -f "$USERS_DB" ]

}



# =============================================================
# Usuário existe?
# =============================================================

user_exists()
{

    local USERNAME="$1"

    jq -e \
        --arg u "$USERNAME" \
        '.users[] | select(.username==$u)' \
        "$USERS_DB" >/dev/null

}



# =============================================================
# Usuário habilitado?
# =============================================================

user_enabled()
{

    local USERNAME="$1"

    jq -r \
        --arg u "$USERNAME" \
        '.users[]
        | select(.username==$u)
        | .enabled' \
        "$USERS_DB"

}



# =============================================================
# Perfil
# =============================================================

user_role()
{

    local USERNAME="$1"

    jq -r \
        --arg u "$USERNAME" \
        '.users[]
        | select(.username==$u)
        | .role' \
        "$USERS_DB"

}



# =============================================================
# Nome exibido
# =============================================================

display_name()
{

    local USERNAME="$1"

    jq -r \
        --arg u "$USERNAME" \
        '.users[]
        | select(.username==$u)
        | .display_name' \
        "$USERS_DB"

}



# =============================================================
# Atualizar último login
# =============================================================

update_last_login()
{

    local USERNAME="$1"

    TMP=$(mktemp)

    jq \
        --arg u "$USERNAME" \
        --arg d "$(date -Iseconds)" \
        '
        .users |= map(
            if .username==$u
            then .last_login=$d
            else .
            end
        )
        ' \
        "$USERS_DB" > "$TMP"

    mv "$TMP" "$USERS_DB"

}



# =============================================================
# Autenticação
# =============================================================

authenticate()
{

    local USERNAME="$1"

    local PASSWORD_TEXT="$2"



    if ! db_exists
    then
        return $AUTH_INVALID_USER
    fi



    if ! user_exists "$USERNAME"
    then

        "$LOGGER" warning \
        "Tentativa login usuário inexistente: $USERNAME"

        return $AUTH_INVALID_USER

    fi



    if [ "$(user_enabled "$USERNAME")" != "true" ]
    then

        "$LOGGER" warning \
        "Usuário desabilitado: $USERNAME"

        return $AUTH_DISABLED

    fi



    if ! "$LOCKOUT" check "$USERNAME"
    then

        return $AUTH_LOCKED

    fi



    if ! "$PASSWORD" verify \
        "$USERNAME" \
        "$PASSWORD_TEXT"
    then

        "$LOCKOUT" fail "$USERNAME"

        "$LOGGER" warning \
        "Senha inválida: $USERNAME"

        return $AUTH_INVALID_PASSWORD

    fi



    "$LOCKOUT" success "$USERNAME"



    update_last_login "$USERNAME"



    "$LOGGER" info \
    "Login efetuado: $USERNAME"



    return $AUTH_OK

}



# =============================================================
# Informações do usuário
# =============================================================

info()
{

    local USERNAME="$1"

    jq \
      --arg u "$USERNAME" \
      '.users[]
      | select(.username==$u)
      | {
            username,
            display_name,
            role,
            enabled,
            last_login
        }' \
      "$USERS_DB"

}



# =============================================================
# CLI
# =============================================================

case "$1" in

auth)

authenticate "$2" "$3"

exit $?

;;

exists)

user_exists "$2"

;;

role)

user_role "$2"

;;

info)

info "$2"

;;

*)

cat <<EOF

DSM Authentication Manager

Uso:

auth_manager.sh auth usuario senha

auth_manager.sh exists usuario

auth_manager.sh role usuario

auth_manager.sh info usuario

EOF

;;

esac