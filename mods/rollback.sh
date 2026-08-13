#!/bin/bash
# =============================================================
# mods/rollback.sh - MÓDULO 03 (MODS)
# Sistema de snapshot e restauração de mods.
# Responsável por:
# - salvar versão anterior antes do update
# - restaurar versão anterior
# - limpar snapshots antigos
# Integra:
# - updater.sh
# - state.sh
# - lock.sh
# =============================================================

LOG_MODULE="mods"
MODS_SNAPSHOT_DIR="${DSM_ROOT}/cache/mods_prev"

# =============================================================
# Validação ID
# =============================================================
rollback_validate_id()
{
    [[ "$1" =~ ^[0-9]+$ ]]
}

# =============================================================
# Criar snapshot
# Uso:
# rollback_snapshot <id> <folder>
# =============================================================
rollback_snapshot()
{
    local id="$1"
    local folder="$2"

    if ! rollback_validate_id "$id"
    then
        log_error \
        "ID inválido para rollback: $id"
        return 1
    fi

    local src
    src="$LGSM_DIR/mods/$folder"

    if [ ! -d "$src" ]
    then
        log_warn \
        "Mod $id não possui pasta para snapshot"
        return 0
    fi

    if ! lock_acquire "rollback-$id"
    then
        log_warn \
        "Rollback do mod $id já está em execução"
        return 1
    fi

    mkdir -p "$MODS_SNAPSHOT_DIR"

    local dest
    dest="$MODS_SNAPSHOT_DIR/$id"

    rm -rf "$dest"

    if command -v rsync >/dev/null 2>&1
    then
        rsync -a \
        "$src/" \
        "$dest/"
    else
        cp -a \
        "$src" \
        "$dest"
    fi

    if [ ! -d "$dest" ]
    then
        log_error \
        "Falha ao criar snapshot do mod $id"
        lock_release "rollback-$id"
        return 1
    fi

    echo "$folder" \
    > "$MODS_SNAPSHOT_DIR/${id}.folder"

    cat > "$MODS_SNAPSHOT_DIR/${id}.info" <<EOF
{
 "id":"$id",
 "folder":"$folder",
 "created":"$(date -Iseconds)"
}
EOF

    log_debug \
    "Snapshot criado para mod $id"

    events_emit \
    "mods.snapshot_created" \
    "Snapshot criado para $id"

    lock_release "rollback-$id"
    return 0
}

# =============================================================
# Verifica snapshot existente
# =============================================================
rollback_has_snapshot()
{
    local id="$1"
    [ -d "$MODS_SNAPSHOT_DIR/$id" ] && \
    [ -f "$MODS_SNAPSHOT_DIR/${id}.folder" ]
}

# =============================================================
# Restaurar snapshot
# Uso:
# rollback_restore <id>
# =============================================================
rollback_restore()
{
    local id="$1"
    if ! rollback_has_snapshot "$id"
    then
        log_error \
        "Nenhum snapshot disponível para $id"
        return 1
    fi

    local folder
    folder="$(cat "$MODS_SNAPSHOT_DIR/${id}.folder")"

    local src
    src="$MODS_SNAPSHOT_DIR/$id"

    local dest
    dest="$LGSM_DIR/mods/$folder"

    if ! lock_acquire "rollback-$id"
    then
        log_warn \
        "Rollback já executando para $id"
        return 1
    fi

    rm -rf "$dest"
    mkdir -p "$dest"

    if command -v rsync >/dev/null 2>&1
    then
        rsync -a \
        "$src/" \
        "$dest/"
    else
        cp -a \
        "$src/"* \
        "$dest/"
    fi

    if [ ! -d "$dest" ]
    then
        log_error \
        "Falha ao restaurar mod $id"
        lock_release "rollback-$id"
        return 1
    fi

    log_ok \
    "Mod $id restaurado (pasta $folder)"

    events_emit \
    "mods.rollback" \
    "Mod $id restaurado"

    lock_release "rollback-$id"
    return 0
}

# =============================================================
# Remove snapshot
# =============================================================
rollback_clear()
{
    local id="$1"
    rm -rf \
    "${MODS_SNAPSHOT_DIR:?}/$id" \
    "${MODS_SNAPSHOT_DIR:?}/${id}.folder" \
    "${MODS_SNAPSHOT_DIR:?}/${id}.info"

    log_debug \
    "Snapshot removido: $id"
}
