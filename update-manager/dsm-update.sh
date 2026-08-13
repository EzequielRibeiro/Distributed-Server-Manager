#!/bin/bash
# =============================================================
# DSM UPDATE MANAGER
# MÓDULO 11
#
# Atualizador oficial DSM via GitHub
# =============================================================

set -e

BASE_DIR="$(dirname "$0")"

source "$BASE_DIR/config.conf"
source "$BASE_DIR/github-client.sh"

if [ "$EUID" -ne 0 ]; then
    echo "Execute como root."
    exit 1
fi

echo "========================================="
echo " DSM UPDATE MANAGER - MÓDULO 11"
echo "========================================="

CURRENT_VERSION=$(cat "$INSTALL_DIR/version")

echo
echo "Versão instalada:"
echo "$CURRENT_VERSION"

echo
echo "Consultando GitHub..."

RELEASE=$(get_latest_release)
LATEST_VERSION=$(get_version "$RELEASE")

if [ -z "$LATEST_VERSION" ]; then
    echo "Não foi possível obter versão."
    exit 1
fi

echo
echo "Última versão:"
echo "$LATEST_VERSION"

if [ "$CURRENT_VERSION" == "$LATEST_VERSION" ]; then
    echo
    echo "DSM já está atualizado."
    exit 0
fi

echo
echo "Nova versão encontrada."

read -rp "Atualizar agora? (s/N): " CONFIRM

if [[ "$CONFIRM" != "s" &&
      "$CONFIRM" != "S" ]]; then
    echo "Cancelado."
    exit 0
fi

DOWNLOAD_URL=$(get_download_url "$RELEASE")

if [ -z "$DOWNLOAD_URL" ]; then
    echo "Arquivo de atualização não encontrado."
    exit 1
fi

echo
echo "Baixando atualização..."

UPDATE_PACKAGE=$(
"$BASE_DIR/download-release.sh" \
"$DOWNLOAD_URL"
)

echo
echo "Pacote:"
echo "$UPDATE_PACKAGE"

echo
echo "Preparando atualização..."

TEMP_DIR="/tmp/dsm-update"

rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

tar -xzf \
"$UPDATE_PACKAGE" \
-C "$TEMP_DIR"

echo
echo "Executando Módulo 10..."

"$UPDATE_SCRIPT" "$TEMP_DIR"

mkdir -p "$(dirname "$HISTORY_FILE")"

echo "$(date '+%Y-%m-%d %H:%M:%S') \
$CURRENT_VERSION -> $LATEST_VERSION" \
>> "$HISTORY_FILE"

echo
echo "========================================="
echo " Atualização concluída"
echo " DSM $LATEST_VERSION"
echo "========================================="
