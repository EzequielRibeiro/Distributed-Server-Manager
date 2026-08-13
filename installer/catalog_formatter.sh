#!/usr/bin/env bash
# Human-readable renderer for canonical catalog JSON documents.
set -Eeuo pipefail

formatter_line(){ printf '%*s\n' 76 '' | tr ' ' '-'; }
formatter_title(){ printf '\n'; formatter_line; printf ' %s\n' "$1"; formatter_line; }
formatter_value(){ printf ' %-18s %s\n' "$1" "$2"; }
formatter_join(){ jq -r "$1 | if type==\"array\" then join(\", \") else (. // \"-\" | tostring) end"; }

format_runtime_list()
{
    formatter_title "AMBIENTES DE EXECUÇÃO DISPONÍVEIS"
    printf ' %-31s %-9s %-12s %-10s %s\n' "ID" "EDIÇÃO" "VARIANTE" "ENGINE" "LOADER"
    formatter_line
    jq -r '.[] | [.id,.edition,.variant,.process.engine,(.loader // "-")] | @tsv' |
      while IFS=$'\t' read -r ID EDITION VARIANT ENGINE LOADER; do
        printf ' %-31s %-9s %-12s %-10s %s\n' "$ID" "$EDITION" "$VARIANT" "$ENGINE" "$LOADER"
      done
}

format_content_list()
{
    formatter_title "CONTEÚDOS DISPONÍVEIS"
    printf ' %-31s %-9s %-9s %-16s %s\n' "ID" "TIPO" "VERSÃO" "LOADER" "MC"
    formatter_line
    jq -r '.[] | [.id,.content_type,.version,((.compatibility.loaders // [])|join(",")),((.compatibility.game_versions // [])|join(","))] | @tsv' |
      while IFS=$'\t' read -r ID TYPE VERSION LOADERS VERSIONS; do
        printf ' %-31s %-9s %-9s %-16s %s\n' "$ID" "$TYPE" "$VERSION" "${LOADERS:--}" "${VERSIONS:--}"
      done
}

format_definition()
{
    local JSON KIND
    JSON="$(cat)"; KIND="$(jq -r '.kind' <<<"${JSON}")"
    formatter_title "${KIND}"
    formatter_value "ID" "$(jq -r '.id' <<<"${JSON}")"
    formatter_value "Nome" "$(jq -r '.name // "-"' <<<"${JSON}")"
    formatter_value "Jogo" "$(jq -r '.game' <<<"${JSON}")"
    if [[ "${KIND}" == "RuntimeDefinition" ]]; then
        formatter_value "Edição / variante" "$(jq -r '.edition + " / " + .variant' <<<"${JSON}")"
        formatter_value "Loader" "$(jq -r '.loader // "-"' <<<"${JSON}")"
        formatter_value "Processo" "$(jq -r '.process.engine + " → " + .process.executable' <<<"${JSON}")"
        formatter_value "Resolver" "$(jq -r '.version.resolver // "-"' <<<"${JSON}")"
        formatter_value "Artifact provider" "$(jq -r '.artifact.provider' <<<"${JSON}")"
        formatter_value "Sistemas" "$(jq -r '.requirements.os|join(", ")' <<<"${JSON}")"
        formatter_value "Arquiteturas" "$(jq -r '.requirements.architectures|join(", ")' <<<"${JSON}")"
        formatter_value "Java" "$(jq -r 'if .requirements.java==null then "não requerido" else ((.requirements.java.min|tostring)+"–"+(.requirements.java.max|tostring)) end' <<<"${JSON}")"
    else
        formatter_value "Tipo / versão" "$(jq -r '.content_type + " / " + .version' <<<"${JSON}")"
        formatter_value "Catalog provider" "$(jq -r '.catalog.provider' <<<"${JSON}")"
        formatter_value "Artifact provider" "$(jq -r '.artifact.provider' <<<"${JSON}")"
        formatter_value "Edições" "$(jq -r '.compatibility.editions|join(", ")' <<<"${JSON}")"
        formatter_value "Loaders" "$(jq -r '(.compatibility.loaders // [])|join(", ")|if length==0 then "-" else . end' <<<"${JSON}")"
        formatter_value "Minecraft" "$(jq -r '.compatibility.game_versions|join(", ")' <<<"${JSON}")"
        formatter_value "Dependências" "$(jq -r '[.dependencies[].id]|join(", ")|if length==0 then "nenhuma" else . end' <<<"${JSON}")"
        formatter_value "Conflitos" "$(jq -r '[.conflicts[].id]|join(", ")|if length==0 then "nenhum" else . end' <<<"${JSON}")"
    fi
    formatter_line
}

format_selection()
{
    local JSON; JSON="$(cat)"
    formatter_title "SELEÇÃO DE AMBIENTE DE EXECUÇÃO"
    formatter_value "Ambiente" "$(jq -r '.runtime_definition // "-"' <<<"${JSON}")"
    formatter_value "Jogo" "$(jq -r '.game' <<<"${JSON}")"
    formatter_value "Edição / variante" "$(jq -r '.edition + " / " + .variant' <<<"${JSON}")"
    formatter_value "Versão / build" "$(jq -r '.version + " / " + (.build|tostring)' <<<"${JSON}")"
    formatter_value "Engine" "$(jq -r '.process_engine' <<<"${JSON}")"
    formatter_value "Provider" "$(jq -r '.provider' <<<"${JSON}")"
    formatter_value "Executável" "$(jq -r '.executable' <<<"${JSON}")"
    formatter_value "Destino" "$(jq -r '.install_dir' <<<"${JSON}")"
    formatter_line
}

format_compatibility()
{
    local JSON OK MARK TITLE
    JSON="$(cat)"; OK="$(jq -r '.compatible' <<<"${JSON}")"
    if [[ "${OK}" == true ]]; then MARK="✓"; TITLE="COMPATÍVEL — INSTALAÇÃO PERMITIDA"; else MARK="✗"; TITLE="INCOMPATÍVEL — INSTALAÇÃO BLOQUEADA"; fi
    formatter_title "${MARK} ${TITLE}"
    formatter_value "Runtime" "$(jq -r '.runtime' <<<"${JSON}")"
    formatter_value "Conteúdo" "$(jq -r '.content|join(", ")|if length==0 then "nenhum" else . end' <<<"${JSON}")"
    if [[ "${OK}" != true ]]; then
        printf '\n Motivos:\n'
        jq -r '.errors[] | "   ✗ \(.code): \(.content)\n     esperado: \(.expected|tojson)\n     atual:    \(.actual|tojson)"' <<<"${JSON}"
    else
        printf '\n   ✓ Versão, edição e loader\n   ✓ Java, sistema e arquitetura\n   ✓ Dependências e conflitos\n'
    fi
    formatter_line
}

format_plan()
{
    local JSON; JSON="$(cat)"
    formatter_title "PLANO DE INSTALAÇÃO"
    formatter_value "Instância" "$(jq -r '.instance' <<<"${JSON}")"
    formatter_value "Runtime" "$(jq -r '.runtime' <<<"${JSON}")"
    printf '\n %-4s %-31s %-10s %s\n' "#" "CONTEÚDO" "TIPO" "VERSÃO"
    formatter_line
    jq -r '.operations|to_entries[]|[(.key+1),.value.content_id,.value.content_type,.value.version]|@tsv' <<<"${JSON}" |
      while IFS=$'\t' read -r N ID TYPE VERSION; do printf ' %-4s %-31s %-10s %s\n' "$N" "$ID" "$TYPE" "$VERSION"; done
    formatter_line
}

format_content_lock()
{
    local JSON; JSON="$(cat)"
    formatter_title "CONTEÚDO INSTALADO"
    formatter_value "Geração" "$(jq -r '.generation // "-"' <<<"${JSON}")"
    printf '\n %-31s %-10s %-10s %s\n' "ID" "TIPO" "VERSÃO" "PROVIDER"
    formatter_line
    jq -r '.entries[]?|[.id,.type,.version,.provider]|@tsv' <<<"${JSON}" |
      while IFS=$'\t' read -r ID TYPE VERSION PROVIDER; do printf ' %-31s %-10s %-10s %s\n' "$ID" "$TYPE" "$VERSION" "$PROVIDER"; done
    formatter_line
}

format_providers()
{
    local JSON; JSON="$(cat)"
    formatter_title "PROVIDERS DO CATÁLOGO"
    jq -r '.providers[] | " ✓ \(.id)  [\(.role)]"' <<<"${JSON}"
    printf '\n Artifact providers:\n'
    jq -r '.artifact_providers[] | "   • \(.)"' <<<"${JSON}"
    formatter_line
}

case "${1:-}" in
    runtime-list) format_runtime_list ;;
    content-list) format_content_list ;;
    definition) format_definition ;;
    selection) format_selection ;;
    compatibility) format_compatibility ;;
    plan) format_plan ;;
    content-lock) format_content_lock ;;
    providers) format_providers ;;
    *) echo "Unknown formatter: ${1:-}" >&2; exit 2 ;;
esac
