#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROVIDER="${ROOT}/installer/providers/steam.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

export DSM_ROOT="${TMP}"

mkdir -p \
    "${TMP}/tools/steamcmd/linux32" \
    "${TMP}/config/providers"

cat > "${TMP}/tools/steamcmd/steamcmd.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

cat > "${TMP}/tools/steamcmd/linux32/steamcmd" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

chmod +x "${TMP}/tools/steamcmd/steamcmd.sh"
chmod +x "${TMP}/tools/steamcmd/linux32/steamcmd"

# shellcheck source=/dev/null
source "${PROVIDER}"

echo "===== Steam provider permission test ====="

if ! steam_provider_validate
then
    echo "FAIL: instalação executável deveria ser válida." >&2
    exit 1
fi

echo "PASS: instalação executável aceita."

chmod -x "${TMP}/tools/steamcmd/linux32/steamcmd"

if steam_provider_validate >/dev/null 2>&1
then
    echo "FAIL: binário interno sem +x foi aceito." >&2
    exit 1
fi

echo "PASS: binário interno sem +x rejeitado."

chmod +x "${TMP}/tools/steamcmd/linux32/steamcmd"

if ! steam_provider_validate
then
    echo "FAIL: restauração de +x não foi reconhecida." >&2
    exit 1
fi

echo "PASS: permissão +x restaurada."

echo
echo "Steam provider permission tests passed."