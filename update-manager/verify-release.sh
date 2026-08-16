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
ARCHIVE_INSPECTOR="$DSM_ROOT/core/archive_inspector.py"
SEMVER_LIB="$DSM_ROOT/core/semver.sh"
ARCHIVE_SECURITY_LIB="$DSM_ROOT/core/archive_security.sh"

if [[ ! -f "$SEMVER_LIB" ]]
then
    log_error "Biblioteca SemVer não encontrada: $SEMVER_LIB"
    return 1 2>/dev/null || exit 1
fi

if [[ ! -f "$ARCHIVE_SECURITY_LIB" ]]
then
    log_error "Biblioteca de segurança de arquivos não encontrada: $ARCHIVE_SECURITY_LIB"
    return 1 2>/dev/null || exit 1
fi

if [[ ! -f "$ARCHIVE_INSPECTOR" ]]
then
    log_error "Inspetor de arquivos não encontrado: $ARCHIVE_INSPECTOR"
    return 1 2>/dev/null || exit 1
fi

# shellcheck source=core/semver.sh
source "$SEMVER_LIB"

# shellcheck source=core/archive_security.sh
source "$ARCHIVE_SECURITY_LIB"

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
                log_error \
                "Checksum SHA256 não fornecido."
                return 1
            fi

    fi

    # =========================================================
    # Validação segura da estrutura do arquivo
    # =========================================================

    echo
    echo "Validando segurança da estrutura DSM..."

    local ARCHIVE_MEMBER
    local ARCHIVE_TARGET
    local ARCHIVE_TYPE
    local RELEASE_ROOT
    local INSPECTION_FILE
    local -a ARCHIVE_MEMBERS=()

    INSPECTION_FILE="$(mktemp)" || {
        log_error \
            "Não foi possível criar arquivo temporário para inspeção."
        return 1
    }

    if ! python3 "$ARCHIVE_INSPECTOR" "$FILE" >"$INSPECTION_FILE"
    then
        log_error \
            "Não foi possível inspecionar os metadados do pacote."
        rm -f -- "$INSPECTION_FILE"
        return 1
    fi

    while IFS=$'\t' read -r \
        ARCHIVE_TYPE ARCHIVE_MEMBER ARCHIVE_TARGET
    do
        if [[ -z "$ARCHIVE_MEMBER" ]]
        then
            log_error \
                "Pacote contém membro sem nome."
            rm -f -- "$INSPECTION_FILE"
            return 1
        fi

        case "$ARCHIVE_TYPE" in
            member)
                if ! archive_validate_member "$ARCHIVE_MEMBER"
                then
                    log_error \
                        "Pacote contém caminho inseguro:"
                    echo "$ARCHIVE_MEMBER"
                    rm -f -- "$INSPECTION_FILE"
                    return 1
                fi
                ;;

            symlink)
                if ! archive_validate_symlink \
                    "$ARCHIVE_MEMBER" "$ARCHIVE_TARGET"
                then
                    log_error \
                        "Pacote contém link simbólico inseguro:"
                    echo "$ARCHIVE_MEMBER -> $ARCHIVE_TARGET"
                    rm -f -- "$INSPECTION_FILE"
                    return 1
                fi
                ;;

            hardlink)
                if ! archive_validate_hardlink \
                    "$ARCHIVE_MEMBER" "$ARCHIVE_TARGET"
                then
                    log_error \
                        "Pacote contém hard link inseguro:"
                    echo "$ARCHIVE_MEMBER -> $ARCHIVE_TARGET"
                    rm -f -- "$INSPECTION_FILE"
                    return 1
                fi
                ;;

            *)
                log_error \
                    "Pacote contém tipo de membro desconhecido:"
                echo "$ARCHIVE_TYPE"
                rm -f -- "$INSPECTION_FILE"
                return 1
                ;;
        esac

        ARCHIVE_MEMBERS+=("$ARCHIVE_MEMBER")

    done <"$INSPECTION_FILE"

    rm -f -- "$INSPECTION_FILE"

    if (( ${#ARCHIVE_MEMBERS[@]} == 0 ))
    then
        log_error \
            "Pacote não contém membros válidos."
        return 1
    fi

    if ! RELEASE_ROOT=$(
        archive_release_members_root "${ARCHIVE_MEMBERS[@]}"
    )
    then
        log_error \
            "Pacote possui estrutura de release inválida."
        return 1
    fi

    echo "Raiz da release validada:"
    echo "$RELEASE_ROOT"

    # =========================================================
    # Extração temporária após validação
    # =========================================================

    TEMP_VERIFY="/tmp/dsm-verify"

    rm -rf "$TEMP_VERIFY"
    mkdir -p "$TEMP_VERIFY"

    tar -xzf "$FILE" \
        -C "$TEMP_VERIFY"

    PACKAGE_ROOT="$TEMP_VERIFY/$RELEASE_ROOT"

    if [ ! -f "$PACKAGE_ROOT/version" ]
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
