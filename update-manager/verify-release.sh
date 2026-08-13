#!/bin/bash
# =============================================================
# verify-release.sh
#
# MÓDULO 11 - DSM UPDATE MANAGER
#
# Responsável por:
# - validar pacote DSM
# - validar checksum SHA256
# - validar estrutura do release
#
# =============================================================

source "$DSM_ROOT/update-manager/config.conf"

# =============================================================
# Validação principal
# =============================================================

verify_release()
{
    local FILE="$1"
    local CHECKSUM="$2"

    # =========================================================
    # Arquivo existe?
    # =========================================================

    if [ -z "$FILE" ]
    then
        log_error \
        "Arquivo não informado."
        return 1
    fi

    if [ ! -f "$FILE" ]
    then
        log_error \
        "Arquivo não encontrado:"
        echo "$FILE"
        return 1
    fi

    # =========================================================
    # Verifica integridade TAR
    # =========================================================

    echo
    echo "Verificando pacote TAR..."

    if ! tar -tzf "$FILE" >/dev/null 2>&1
    then
        log_error \
        "Pacote TAR corrompido."
        return 1
    fi

    echo "Arquivo TAR válido."

    # =========================================================
    # Verificação SHA256
    # =========================================================

    if [ "$VERIFY_CHECKSUM" = "1" ]
    then

        if [ -n "$CHECKSUM" ]
        then
            echo
            echo "Validando SHA256..."

            echo "$CHECKSUM  $FILE" |
            sha256sum -c -

            if [ $? -ne 0 ]
            then
                log_error \
                "Checksum inválido."
                return 1
            fi

            echo "Checksum OK."

        else
            echo
            echo "Aviso:"
            echo "Checksum não fornecido."
            echo "Continuando sem validação SHA256."

        fi

    fi

    # =========================================================
    # Validação estrutura DSM
    # =========================================================

    echo
    echo "Validando estrutura DSM..."

    TEMP_VERIFY="/tmp/dsm-verify"

    rm -rf "$TEMP_VERIFY"
    mkdir -p "$TEMP_VERIFY"

    tar -xzf "$FILE" \
    -C "$TEMP_VERIFY"

    PACKAGE_ROOT=$(find "$TEMP_VERIFY" \
    -name version \
    -printf "%h\n" \
    | head -1)

    if [ -z "$PACKAGE_ROOT" ]
    then
        log_error \
        "Pacote sem arquivo version."
        rm -rf "$TEMP_VERIFY"
        return 1
    fi

    REQUIRED_FILES="
version
bin/dsm
core/bootstrap.sh
"

    for ITEM in $REQUIRED_FILES
    do

        if [ ! -e "$PACKAGE_ROOT/$ITEM" ]
        then
            log_error \
            "Arquivo obrigatório ausente:"
            echo "$ITEM"

            rm -rf "$TEMP_VERIFY"
            return 1

        fi

    done

    rm -rf "$TEMP_VERIFY"

    echo
    echo "Estrutura DSM válida."

    return 0
}
