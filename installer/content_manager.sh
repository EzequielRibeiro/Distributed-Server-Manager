#!/usr/bin/env bash
# Capivara DSM - Transactional instance content manager v2
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_ROOT="${DSM_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
PLANNER="${DSM_ROOT}/installer/content_planner.sh"
CONTENT_ROOT="${DSM_CATALOG_ROOT:-${DSM_ROOT}/catalog/v2}/content"
FORMATTER="${DSM_ROOT}/installer/catalog_formatter.sh"

# Reuse the Atomic Engine staging cleanup, provider loader and rollback contract.
source "${DSM_ROOT}/installer/atomic_install.sh"

content_error(){ echo "[DSM][CONTENT][ERROR] $*" >&2; }
content_log(){ echo "[DSM][CONTENT] $*"; }
content_jq_r(){ jq -r "$@" | tr -d '\r'; }
content_render_lock()
{
    if [[ "${DSM_OUTPUT_FORMAT:-human}" == "json" ]]; then jq . "$1"; else "${FORMATTER}" content-lock <"$1"; fi
}
content_render_status()
{
    local ACTION="$1" INSTANCE="$2" DETAIL="${3:-}"
    if [[ "${DSM_OUTPUT_FORMAT:-human}" == "json" ]]; then
        jq -n --arg action "${ACTION}" --arg instance "${INSTANCE}" --arg detail "${DETAIL}" \
          '{schema_version:2,kind:"ContentOperationResult",success:true,action:$action,instance:$instance,detail:(if $detail=="" then null else $detail end)}'
    else
        printf '\n----------------------------------------------------------------------------\n'
        printf ' ✓ OPERAÇÃO DE CONTEÚDO CONCLUÍDA\n'
        printf '%-20s %s\n' ' Ação' "${ACTION}"
        printf '%-20s %s\n' ' Instância' "${INSTANCE}"
        [[ -z "${DETAIL}" ]] || printf '%-20s %s\n' ' Conteúdo' "${DETAIL}"
        printf '%s\n' '----------------------------------------------------------------------------'
    fi
}

content_root(){ printf '%s/content\n' "$1"; }
content_lock(){ printf '%s/.dsm/content-lock.json\n' "$(content_root "$1")"; }
instance_manifest(){ printf '%s/.dsm/instance-manifest.json\n' "$1"; }

content_validate_instance()
{
    local INSTANCE="$1"
    [[ -n "${INSTANCE}" && "${INSTANCE}" == /* && "${INSTANCE}" != "/" ]] || {
        content_error "Instance path must be an absolute non-root path."
        return 1
    }
    [[ "${INSTANCE}" != *$'\n'* && "${INSTANCE}" != *$'\r'* ]]
}

content_definition()
{
    local ID="$1" FILE
    while IFS= read -r -d '' FILE; do
        if jq -e --arg id "${ID}" '.id==$id' "${FILE}" >/dev/null; then printf '%s\n' "${FILE}"; return 0; fi
    done < <(find "${CONTENT_ROOT}" -type f -name '*.json' -print0)
    return 1
}

content_generation()
{
    local LOCK
    LOCK="$(content_lock "$1")"
    if [[ -f "${LOCK}" ]]; then content_jq_r '(.generation // 0) + 1' "${LOCK}"; else echo 1; fi
}

content_stage_current()
{
    local INSTANCE="$1" ROOT NEW
    ROOT="$(content_root "${INSTANCE}")"; NEW="${ROOT}.new"
    atomic_cleanup_staging "${NEW}" || return 1
    mkdir -p "${NEW}/mods" "${NEW}/plugins" "${NEW}/modpacks" "${NEW}/.dsm"
    if [[ -d "${ROOT}" ]]; then cp -a -- "${ROOT}/." "${NEW}/"; fi
}

content_resolve_package()
{
    local PACKAGE="$1"
    if [[ "${PACKAGE}" == /* ]]; then printf '%s\n' "${PACKAGE}"; else printf '%s/%s\n' "${DSM_ROOT}" "${PACKAGE}"; fi
}

content_apply_install_operation()
{
    local OP="$1" NEW="$2"
    local ID TARGET PROVIDER PACKAGE VERSION DEST
    local FILENAME SHA256 SHA512 SHA1

    ID="$(content_jq_r '.content_id' <<<"${OP}")"
    TARGET="$(content_jq_r '.target' <<<"${OP}")"
    PROVIDER="$(content_jq_r '.artifact.provider' <<<"${OP}")"
    PACKAGE="$(content_jq_r '.artifact.package_id // .artifact.url // empty' <<<"${OP}")"
    VERSION="$(content_jq_r '.version // empty' <<<"${OP}")"

    FILENAME="$(content_jq_r '.artifact.filename // empty' <<<"${OP}")"
    SHA256="$(content_jq_r '.artifact.sha256 // empty' <<<"${OP}")"
    SHA512="$(content_jq_r '.artifact.sha512 // empty' <<<"${OP}")"
    SHA1="$(content_jq_r '.artifact.sha1 // empty' <<<"${OP}")"

    [[ -n "${ID}" ]] || {
        content_error "Missing content_id."
        return 2
    }

    [[ -n "${PROVIDER}" ]] || {
        content_error "Missing artifact provider for ${ID}."
        return 2
    }

    [[ -n "${PACKAGE}" ]] || {
        content_error "Missing artifact package for ${ID}."
        return 2
    }

    [[ -n "${TARGET}" &&
       "${TARGET}" != /* &&
       "${TARGET}" != *".."* ]] || {
        content_error "Unsafe target: ${TARGET}"
        return 1
    }

    if [[ "${PROVIDER}" == "local" ]]; then
        PACKAGE="$(content_resolve_package "${PACKAGE}")"
    fi

    DEST="${NEW}/${TARGET}"

    #
    # TARGET representa o diretório lógico da categoria.
    #
    # Vários conteúdos podem compartilhar, por exemplo:
    #
    #   mods/
    #   plugins/
    #
    # Portanto NÃO removemos DEST aqui. O staging completo já foi
    # preparado por content_stage_current().
    #
    mkdir -p "${DEST}"

    provider_require "${PROVIDER}" || return 1

    #
    # Limpa metadados herdados de uma operação anterior.
    #
    unset DSM_CONTENT_FILENAME
    unset DSM_CONTENT_SHA512
    unset DSM_CONTENT_SHA1
    unset DSM_HTTP_FILENAME
    unset DSM_HTTP_SHA256
    unset DSM_HTTP_VERSION
    unset DSM_LOCAL_SHA256
    unset DSM_LOCAL_VERSION

    if [[ -n "${FILENAME}" ]]; then
        DSM_CONTENT_FILENAME="${FILENAME}"
        DSM_HTTP_FILENAME="${FILENAME}"
        export DSM_CONTENT_FILENAME DSM_HTTP_FILENAME
    fi

    if [[ -n "${SHA512}" ]]; then
        DSM_CONTENT_SHA512="${SHA512}"
        export DSM_CONTENT_SHA512
    fi

    if [[ -n "${SHA1}" ]]; then
        DSM_CONTENT_SHA1="${SHA1}"
        export DSM_CONTENT_SHA1
    fi

    if [[ -n "${SHA256}" ]]; then
        DSM_HTTP_SHA256="${SHA256}"
        DSM_LOCAL_SHA256="${SHA256}"
        export DSM_HTTP_SHA256 DSM_LOCAL_SHA256
    fi

    DSM_HTTP_VERSION="${VERSION}"
    DSM_LOCAL_VERSION="${VERSION}"
    DSM_CONTENT_VERSION="${VERSION}"

    export DSM_HTTP_VERSION
    export DSM_LOCAL_VERSION
    export DSM_CONTENT_VERSION

    provider_install "${PACKAGE}" "${DEST}" anonymous || {
        content_error "Provider ${PROVIDER} failed installing ${ID}."
        return 1
    }

    content_log "Prepared ${ID} -> ${TARGET}"
}

content_write_lock()
{
    local PLAN="$1" NEW="$2" GENERATION="$3" LOCK PREVIOUS TMP
    LOCK="${NEW}/.dsm/content-lock.json"
    PREVIOUS="${LOCK}.previous"; TMP="${LOCK}.tmp"
    if [[ -f "${LOCK}" ]]; then cp -a -- "${LOCK}" "${PREVIOUS}"; else printf '{"entries":[]}\n' >"${PREVIOUS}"; fi
    jq --argjson generation "${GENERATION}" --slurpfile previous "${PREVIOUS}" '
      ([.operations[] | {
          id:.content_id,type:.content_type,version:.version,
          provider:.artifact.provider,package_id:.artifact.package_id,
          path:.target,sha256:null
        }] as $new |
       ($new|map(.id)) as $new_ids |
       {schema_version:2,kind:"ContentLock",generation:$generation,
        entries:((($previous[0].entries // [])|map(select(.id as $id|$new_ids|index($id)|not))) + $new)})' "${PLAN}" >"${TMP}"
    jq empty "${TMP}" >/dev/null && mv -- "${TMP}" "${LOCK}"
    rm -f -- "${PREVIOUS}"
}

content_write_instance_manifest()
{
    local INSTANCE="$1" RUNTIME="$2" GENERATION="$3" LOCK TMP
    LOCK="$(content_lock "${INSTANCE}")"; TMP="$(instance_manifest "${INSTANCE}").tmp.$$"
    mkdir -p "${INSTANCE}/.dsm"
    jq --arg instance "${INSTANCE}" --arg runtime "${RUNTIME}" \
      --argjson generation "${GENERATION}" --argjson updated_at "$(date +%s)" '
      {schema_version:2,kind:"InstanceManifest",instance:$instance,
       runtime:{id:$runtime},content:[.entries[].id],generation:$generation,
       updated_at:$updated_at}' "${LOCK}" >"${TMP}"
    jq empty "${TMP}" >/dev/null && mv -- "${TMP}" "$(instance_manifest "${INSTANCE}")"
}

content_activate()
{
    local INSTANCE="$1" ROOT NEW OLD
    ROOT="$(content_root "${INSTANCE}")"; NEW="${ROOT}.new"; OLD="${ROOT}.old"
    [[ -d "${NEW}" ]] || return 1
    rm -rf -- "${OLD}"
    if [[ -d "${ROOT}" ]]; then mv -- "${ROOT}" "${OLD}" || return 1; fi
    if ! mv -- "${NEW}" "${ROOT}"; then
        [[ -d "${OLD}" ]] && mv -- "${OLD}" "${ROOT}"
        return 1
    fi
}

content_verify()
{
    local INSTANCE="$1" ROOT LOCK ID REL_PATH
    content_validate_instance "${INSTANCE}" || return 2
    ROOT="$(content_root "${INSTANCE}")"; LOCK="$(content_lock "${INSTANCE}")"
    [[ -f "${LOCK}" ]] || { content_error "Content lock not found."; return 1; }
    jq -e '.schema_version==2 and .kind=="ContentLock"' "${LOCK}" >/dev/null || return 1
    while IFS=$'\t' read -r ID REL_PATH; do
        [[ -d "${ROOT}/${REL_PATH}" ]] || { content_error "Missing content path for ${ID}: ${REL_PATH}"; return 1; }
    done < <(jq -r '.entries[] | [.id,.path] | @tsv' "${LOCK}" | tr -d '\r')
    content_log "Content lock verified."
}

content_install()
{
    local REQUEST="$1" INSTANCE="$2" TMP_DIR PLAN NEW GENERATION OP
    content_validate_instance "${INSTANCE}" || return 2
    TMP_DIR="$(mktemp -d)"; trap 'rm -rf -- "${TMP_DIR}"' RETURN
    PLAN="${TMP_DIR}/plan.json"
    "${PLANNER}" plan "${REQUEST}" "${INSTANCE}" >"${PLAN}" || return 1
    content_stage_current "${INSTANCE}" || return 1
    NEW="$(content_root "${INSTANCE}").new"
    while IFS= read -r OP; do content_apply_install_operation "${OP}" "${NEW}" || { atomic_cleanup_staging "${NEW}"; return 1; }; done < <(jq -c '.operations[]' "${PLAN}")
    GENERATION="$(content_generation "${INSTANCE}")"
    content_write_lock "${PLAN}" "${NEW}" "${GENERATION}" || { atomic_cleanup_staging "${NEW}"; return 1; }
    content_activate "${INSTANCE}" || return 1
    if ! content_verify "${INSTANCE}"; then
        install_rollback "$(content_root "${INSTANCE}")" || true
        return 1
    fi
    content_write_instance_manifest "${INSTANCE}" "$(jq -r '.runtime' "${PLAN}")" "${GENERATION}" || return 1
    content_render_lock "$(content_lock "${INSTANCE}")"
}

content_remove()
{
    local INSTANCE="$1" ID="$2" ROOT NEW LOCK ENTRY_PATH GENERATION INSTALLED DEP_FILE
    content_validate_instance "${INSTANCE}" || return 2
    ROOT="$(content_root "${INSTANCE}")"; LOCK="$(content_lock "${INSTANCE}")"
    [[ -f "${LOCK}" ]] || { content_error "Content lock not found."; return 1; }
    ENTRY_PATH="$(content_jq_r --arg id "${ID}" '.entries[]|select(.id==$id)|.path' "${LOCK}")"
    [[ -n "${ENTRY_PATH}" ]] || { content_error "Content not installed: ${ID}"; return 1; }
    [[ "${ENTRY_PATH}" != /* && "${ENTRY_PATH}" != *".."* ]] || { content_error "Unsafe lock path: ${ENTRY_PATH}"; return 1; }
    while IFS= read -r INSTALLED; do
        [[ -n "${INSTALLED}" && "${INSTALLED}" != "${ID}" ]] || continue
        DEP_FILE="$(content_definition "${INSTALLED}" 2>/dev/null || true)"
        if [[ -n "${DEP_FILE}" ]] && jq -e --arg id "${ID}" '.dependencies[]?|select(.required!=false and .id==$id)' "${DEP_FILE}" >/dev/null; then
            content_error "Cannot remove ${ID}; required by ${INSTALLED}."
            return 1
        fi
    done < <(jq -r '.entries[].id' "${LOCK}" | tr -d '\r')
    content_stage_current "${INSTANCE}" || return 1; NEW="${ROOT}.new"
    rm -rf -- "${NEW}/${ENTRY_PATH}"
    GENERATION="$(content_generation "${INSTANCE}")"
    jq --arg id "${ID}" --argjson generation "${GENERATION}" '.generation=$generation|.entries|=map(select(.id!=$id))' "${LOCK}" >"${NEW}/.dsm/content-lock.json"
    content_activate "${INSTANCE}" || return 1
    content_verify "${INSTANCE}" || return 1
    content_write_instance_manifest "${INSTANCE}" "$(content_jq_r '.runtime.id // "unknown"' "$(instance_manifest "${INSTANCE}")" 2>/dev/null || echo unknown)" "${GENERATION}"
}

content_rollback()
{
    local INSTANCE="$1" RUNTIME GENERATION
    content_validate_instance "${INSTANCE}" || return 2
    RUNTIME="$(content_jq_r '.runtime.id // "unknown"' "$(instance_manifest "${INSTANCE}")" 2>/dev/null || echo unknown)"
    install_rollback "$(content_root "${INSTANCE}")" || return 1
    content_verify "${INSTANCE}" || return 1
    GENERATION="$(content_jq_r '.generation' "$(content_lock "${INSTANCE}")")"
    content_write_instance_manifest "${INSTANCE}" "${RUNTIME}" "${GENERATION}"
}

content_list_installed()
{
    local INSTANCE="$1"
    local LOCK_FILE

    content_validate_instance "${INSTANCE}" || return 2
    LOCK_FILE="$(content_lock "${INSTANCE}")"

    if [[ ! -f "${LOCK_FILE}" ]]; then
        jq -n \
            --arg instance "${INSTANCE}" \
            '{
                instance: $instance,
                entries: [],
                content: [],
                installed: [],
                total: 0
            }'
        return 0
    fi

    if ! jq empty "${LOCK_FILE}" >/dev/null 2>&1; then
        jq -n \
            --arg instance "${INSTANCE}" \
            '{
                error: "content lock is invalid",
                instance: $instance
            }'
        return 1
    fi

    content_render_lock "${LOCK_FILE}"
}

case "${1:-}" in
    install) [[ $# -eq 3 ]] || exit 2; content_install "$2" "$3" ;;
    remove) [[ $# -eq 3 ]] || exit 2; content_remove "$2" "$3" && content_render_status "remove" "$2" "$3" ;;
    list-installed) [[ $# -eq 2 ]] || exit 2; content_list_installed "$2" ;;
    verify) [[ $# -eq 2 ]] || exit 2; content_verify "$2" && content_render_status "verify" "$2" ;;
    rollback) [[ $# -eq 2 ]] || exit 2; content_rollback "$2" && content_render_status "rollback" "$2" ;;
    *) echo "Usage: content_manager.sh install REQUEST INSTANCE | remove INSTANCE CONTENT_ID | list-installed INSTANCE | verify INSTANCE | rollback INSTANCE" >&2; exit 2 ;;
esac
