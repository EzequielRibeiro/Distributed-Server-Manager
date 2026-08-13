#!/usr/bin/env bash
set -Eeuo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_SOURCE="$INSTALLER_DIR"
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_BIN="$DSM_ROOT/bin/dsm"
DSM_LINK="/usr/local/bin/dsm"
SYSTEMD_DIR="/etc/systemd/system"
CAPIVARA_GITHUB_REPO="${CAPIVARA_GITHUB_REPO:-EzequielRibeiro/Distributed-Server-Manager}"
CAPIVARA_GITHUB_API="${CAPIVARA_GITHUB_API:-https://api.github.com}"
CAPIVARA_RELEASE_TAG="${CAPIVARA_RELEASE_TAG:-latest}"
GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
DSM_SERVICE_USER="${DSM_SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
DSM_SERVICE_GROUP="${DSM_SERVICE_GROUP:-$(id -gn "$DSM_SERVICE_USER")}"
DSM_NODE_ROLE="${DSM_NODE_ROLE:-agent}"
INSTALL_MODE="${DSM_INSTALL_SOURCE:-remote}"
INSTALL_MODE_EXPLICIT=0
[[ -n "${DSM_INSTALL_SOURCE:-}" ]] && INSTALL_MODE_EXPLICIT=1
INSTALL_STEAMCMD="${DSM_INSTALL_STEAMCMD:-auto}"
STEAMCMD_ROOT="${STEAMCMD_ROOT:-/opt/steamcmd}"
ALLOW_REINSTALL=0
DRY_RUN=0
SYSTEMD_ACTIVE=0
BOOTSTRAP_TMP=""

log(){ printf '[Capivara] %s\n' "$*"; }
warn(){ printf '[Capivara][AVISO] %s\n' "$*" >&2; }
die(){ printf '[Capivara][ERRO] %s\n' "$*" >&2; exit 1; }
section(){ printf '\n==============================================================\n %s\n==============================================================\n' "$1"; }
run(){ if ((DRY_RUN)); then printf '[DRY-RUN]'; printf ' %q' "$@"; printf '\n'; else "$@"; fi; }
cleanup(){ [[ -n "$BOOTSTRAP_TMP" && -d "$BOOTSTRAP_TMP" ]] && rm -rf "$BOOTSTRAP_TMP" || true; }
trap cleanup EXIT

usage(){ cat <<'EOF_USAGE'
Uso:
  sudo ./install.sh --local
  sudo ./install.sh --remote
  sudo ./install.sh --version TAG
  sudo ./install.sh --reinstall
  sudo ./install.sh --dry-run [--local|--remote]

Enquanto não houver uma GitHub Release publicada, use --local.
--dry-run valida e descreve o plano sem modificar o sistema.
EOF_USAGE
}

parse_args(){
  while (($#)); do
    case "$1" in
      --local) INSTALL_MODE=local; INSTALL_MODE_EXPLICIT=1; shift;;
      --remote) INSTALL_MODE=remote; INSTALL_MODE_EXPLICIT=1; shift;;
      --version) [[ $# -ge 2 ]] || die '--version requer uma tag'; INSTALL_MODE=remote; INSTALL_MODE_EXPLICIT=1; CAPIVARA_RELEASE_TAG="$2"; shift 2;;
      --reinstall) ALLOW_REINSTALL=1; shift;;
      --dry-run) DRY_RUN=1; shift;;
      --help|-h) usage; exit 0;;
      *) die "Opção desconhecida: $1";;
    esac
  done
  [[ "$INSTALL_MODE" == local || "$INSTALL_MODE" == remote ]] || die "Origem inválida: $INSTALL_MODE"
  [[ "$DSM_NODE_ROLE" == controller || "$DSM_NODE_ROLE" == agent || "$DSM_NODE_ROLE" == hybrid ]] || die "DSM_NODE_ROLE inválido: $DSM_NODE_ROLE"
}

require_root(){ ((DRY_RUN)) || [[ $EUID -eq 0 ]] || die 'Execute como root: sudo ./install.sh'; }
local_source_available(){ [[ -f "$INSTALLER_DIR/bin/dsm" && -f "$INSTALLER_DIR/core/bootstrap.sh" && -f "$INSTALLER_DIR/config/dsm.conf" ]]; }

detect_systemd(){
  if [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
    SYSTEMD_ACTIVE=1
    log 'systemd ativo e acessível.'
  else
    SYSTEMD_ACTIVE=0
    warn 'systemd não está ativo neste ambiente. Serviços serão ignorados; arquivos, banco e CLI ainda podem ser instalados.'
  fi
}

check_commands(){
  local missing=() cmd
  for cmd in bash rsync curl tar python3 getent sha256sum; do command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd"); done
  ((${#missing[@]}==0)) || die "Dependências ausentes: ${missing[*]}. Instale-as antes de executar o instalador."
}

github_headers(){ printf '%s\n' '-H' 'Accept: application/vnd.github+json' '-H' 'X-GitHub-Api-Version: 2022-11-28'; [[ -n "$GH_TOKEN" ]] && printf '%s\n' '-H' "Authorization: Bearer $GH_TOKEN"; }
github_api_get(){ local -a a=(); mapfile -t a < <(github_headers); curl -fsSL "${a[@]}" "$1"; }

acquire_remote_source(){
  section 'Origem remota'
  local endpoint
  if [[ "$CAPIVARA_RELEASE_TAG" == latest ]]; then endpoint="$CAPIVARA_GITHUB_API/repos/$CAPIVARA_GITHUB_REPO/releases/latest"; else endpoint="$CAPIVARA_GITHUB_API/repos/$CAPIVARA_GITHUB_REPO/releases/tags/$CAPIVARA_RELEASE_TAG"; fi
  BOOTSTRAP_TMP="$(mktemp -d -t capivara-installer.XXXXXX)"
  local meta="$BOOTSTRAP_TMP/release.json"
  if ! github_api_get "$endpoint" >"$meta"; then
    die "Nenhuma release utilizável foi encontrada em $CAPIVARA_GITHUB_REPO. A instalação remota foi interrompida antes de alterar $DSM_ROOT. Use --local durante o desenvolvimento ou publique uma GitHub Release."
  fi
  local info tag url
  info="$(python3 - "$meta" <<'PY'
import json,sys
x=json.load(open(sys.argv[1],encoding='utf-8'))
print(x.get('tag_name',''))
print(x.get('tarball_url',''))
PY
)"
  tag="$(sed -n '1p' <<<"$info")"; url="$(sed -n '2p' <<<"$info")"
  [[ -n "$tag" && -n "$url" ]] || die 'Release encontrada, mas sem tarball utilizável.'
  local archive="$BOOTSTRAP_TMP/capivara-$tag.tar.gz"; local -a a=(); mapfile -t a < <(github_headers)
  curl -fL --retry 3 "${a[@]}" -o "$archive" "$url"
  tar -tzf "$archive" >/dev/null || die 'Tarball remoto inválido.'
  mkdir -p "$BOOTSTRAP_TMP/source"; tar -xzf "$archive" -C "$BOOTSTRAP_TMP/source"
  local candidate; candidate="$(find "$BOOTSTRAP_TMP/source" -type f -path '*/bin/dsm' -print -quit)"
  [[ -n "$candidate" ]] || die 'Release não contém bin/dsm.'
  DSM_SOURCE="$(dirname "$(dirname "$candidate")")"
  log "Release $tag preparada."
}

acquire_source(){
  if [[ "$INSTALL_MODE" == local ]]; then local_source_available || die 'Origem local incompleta.'; DSM_SOURCE="$INSTALLER_DIR"; else acquire_remote_source; fi
}

verify_source(){
  local req=(version bin/dsm core/bootstrap.sh config/dsm.conf database/manager.py database/migrations/001_initial.sql) missing=() p
  for p in "${req[@]}"; do [[ -e "$DSM_SOURCE/$p" ]] || missing+=("$p"); done
  ((${#missing[@]}==0)) || die "Pacote incompleto: ${missing[*]}"
}

preflight(){
  section 'Pré-validação'
  check_commands
  detect_systemd
  if [[ "$INSTALL_MODE" == local ]]; then verify_source; fi
  if [[ -e "$DSM_ROOT/version" && $ALLOW_REINSTALL -eq 0 ]]; then die "Instalação existente em $DSM_ROOT. Use update.sh; --reinstall apenas quando intencional."; fi
  log "Repositório remoto: $CAPIVARA_GITHUB_REPO"
  log "Origem: $INSTALL_MODE | node: $DSM_NODE_ROLE | systemd: $SYSTEMD_ACTIVE | dry-run: $DRY_RUN"
}

ensure_account(){
  getent group "$DSM_SERVICE_GROUP" >/dev/null 2>&1 || run groupadd --system "$DSM_SERVICE_GROUP"
  if ! id "$DSM_SERVICE_USER" >/dev/null 2>&1; then run useradd --system --gid "$DSM_SERVICE_GROUP" --home-dir "$DSM_ROOT" --shell /usr/sbin/nologin "$DSM_SERVICE_USER"; fi
}

install_files(){
  run mkdir -p "$DSM_ROOT/config"
  if ((DRY_RUN)); then log "[DRY-RUN] rsync $DSM_SOURCE/ -> $DSM_ROOT/ preservando configurações existentes"; return; fi
  rsync -a --exclude install.sh --exclude config/dsm.conf --exclude config/agent.conf "$DSM_SOURCE/" "$DSM_ROOT/"
  [[ -f "$DSM_ROOT/config/dsm.conf" ]] || cp "$DSM_SOURCE/config/dsm.conf" "$DSM_ROOT/config/dsm.conf"
  find "$DSM_ROOT" -type f -name '*.sh' -exec chmod +x {} \;
  chmod +x "$DSM_BIN"
  mkdir -p "$DSM_ROOT"/{cache,logs,tmp,data,runtime,instances}
}

initialize_database(){
  if ((DRY_RUN)); then log "[DRY-RUN] inicializaria $DSM_ROOT/data/capivara.db"; return; fi
  python3 "$DSM_ROOT/database/manager.py" --root "$DSM_ROOT" --database "$DSM_ROOT/data/capivara.db" init
}

install_cli(){ run ln -sf "$DSM_BIN" "$DSM_LINK"; ((DRY_RUN)) || chmod +x "$DSM_LINK"; }

install_systemd(){
  if ((SYSTEMD_ACTIVE==0)); then warn 'Etapa systemd ignorada de forma segura.'; return; fi
  if ((DRY_RUN)); then log "[DRY-RUN] copiaria unidades para $SYSTEMD_DIR, executaria daemon-reload e enable"; return; fi
  [[ -d "$DSM_ROOT/systemd" ]] || return 0
  local src name dst
  while IFS= read -r -d '' src; do name="$(basename "$src")"; dst="$SYSTEMD_DIR/$name"; cp -f "$src" "$dst"; sed -i -e "s|{{DSM_USER}}|$DSM_SERVICE_USER|g" -e "s|{{DSM_GROUP}}|$DSM_SERVICE_GROUP|g" "$dst"; done < <(find "$DSM_ROOT/systemd" -maxdepth 1 -type f \( -name '*.service' -o -name '*.timer' \) -print0)
  systemctl daemon-reload
  local u; for u in dsm-monitor.service dsm-scheduler.service dsm-alert-engine.service dsm-dashboard.service dsm-dashboard-worker.service dsm-notification-engine.timer dsm-notification-center.timer; do [[ -f "$SYSTEMD_DIR/$u" ]] && systemctl enable "$u"; done
}

install_steamcmd(){
  [[ "$DSM_NODE_ROLE" != controller ]] || return 0
  [[ "$INSTALL_STEAMCMD" != 0 && "$INSTALL_STEAMCMD" != no && "$INSTALL_STEAMCMD" != false ]] || return 0
  command -v steamcmd >/dev/null 2>&1 && return 0
  if ((DRY_RUN)); then log "[DRY-RUN] instalaria SteamCMD em $STEAMCMD_ROOT"; return; fi
  mkdir -p "$STEAMCMD_ROOT"; curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar -xz -C "$STEAMCMD_ROOT"
  [[ -x "$STEAMCMD_ROOT/steamcmd.sh" ]] || die 'Falha ao instalar SteamCMD.'
  ln -sf "$STEAMCMD_ROOT/steamcmd.sh" /usr/local/bin/steamcmd
}

validate(){
  if ((DRY_RUN)); then log 'Dry-run concluído: nenhuma alteração persistente foi executada.'; return; fi
  [[ -x "$DSM_BIN" ]] || die "CLI ausente: $DSM_BIN"
  python3 "$DSM_ROOT/database/manager.py" --root "$DSM_ROOT" check >/dev/null || die 'Banco inválido após instalação.'
  if ((SYSTEMD_ACTIVE)); then local u; for u in dsm-monitor.service dsm-scheduler.service dsm-dashboard.service; do [[ -f "$SYSTEMD_DIR/$u" ]] || die "Unidade ausente: $u"; done; fi
}

main(){
  parse_args "$@"; require_root
  if [[ $INSTALL_MODE_EXPLICIT -eq 0 ]] && local_source_available; then INSTALL_MODE=local; warn 'Nenhuma origem explícita: usando arquivos locais porque o checkout está completo.'; fi
  preflight
  acquire_source
  verify_source
  if ((DRY_RUN)); then ensure_account; install_files; initialize_database; install_cli; install_systemd; install_steamcmd; validate; exit 0; fi
  ensure_account; install_files; initialize_database; install_cli; install_systemd; install_steamcmd; validate
  section 'Capivara DSM instalado com sucesso'
  printf 'Origem: %s\nNode: %s\nSystemd: %s\nComando: %s\n' "$INSTALL_MODE" "$DSM_NODE_ROLE" "$SYSTEMD_ACTIVE" "$DSM_LINK"
}

[[ "${BASH_SOURCE[0]}" != "$0" ]] || main "$@"
