#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
USERS_CLI="$DSM_ROOT/database/users.py"

case "${1:-}" in
    add)
        username="${2:-}"
        role="${3:-}"
        scope="${4:-}"
        [[ -n "$username" && -n "$role" ]] || { echo "Uso: dsm user add <usuario> <admin|operator|controller|customer> [scope]"; exit 2; }
        [[ "$role" != "operador" ]] || role="operator"
        if [[ "$role" == "controller" || "$role" == "customer" ]] && [[ -z "$scope" ]]; then
            echo "Erro: usuários com papel $role exigem o identificador do scope." >&2
            echo "Uso: dsm user add <usuario> $role <scope>" >&2
            exit 2
        fi
        command=(python3 "$USERS_CLI" --root "$DSM_ROOT" create "$username" --role "$role")
        [[ -z "$scope" ]] || command+=(--scope "$scope")
        exec "${command[@]}"
        ;;
    remove)
        [[ -n "${2:-}" ]] || { echo "Uso: dsm user remove <usuario>"; exit 2; }
        exec python3 "$USERS_CLI" --root "$DSM_ROOT" delete "$2"
        ;;
    passwd)
        [[ -n "${2:-}" ]] || { echo "Uso: dsm user passwd <usuario>"; exit 2; }
        exec python3 "$USERS_CLI" --root "$DSM_ROOT" passwd "$2"
        ;;
    list)
        exec python3 "$USERS_CLI" --root "$DSM_ROOT" list
        ;;
    *)
        cat <<'EOF'
Uso:
  dsm user add <usuario> <admin|operator|controller|customer> [scope]
  dsm user remove <usuario>
  dsm user passwd <usuario>
  dsm user list

O primeiro administrador pode ser criado com:
  dsm user add admin admin

O ambiente completo de teste Aurora pode ser criado com:
  dsm instance create-aurora

Se o cliente CLI-DEMO-001 já existir, crie somente o login Aurora com:
  dsm user add aurora customer CLI-DEMO-001
EOF
        ;;
esac
