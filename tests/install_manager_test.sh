#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="${ROOT}/install.sh"
CORE_INSTALLER="${ROOT}/install-core.sh"
CLI="${ROOT}/bin/dsm"
fail(){ echo "FAIL: $*" >&2; exit 1; }
EXPECTED_VERSION=$(tr -d '\r\n' <"${ROOT}/version")
bash -n "${INSTALLER}"; bash -n "${CORE_INSTALLER}"
if grep -qE 'mine|/home/mine' "${ROOT}/config/dsm.conf"; then fail "distributed dsm.conf contains a machine-specific account"; fi
grep -Fq -- '--exclude "config/dsm.conf"' "${CORE_INSTALLER}" || fail "installer overwrites an existing dsm.conf"
grep -Fq -- '--exclude "config/agent.conf"' "${CORE_INSTALLER}" || fail "installer overwrites an existing agent.conf"
grep -Fq 'write_dsm_config' "${CORE_INSTALLER}" || fail "installer does not configure dsm.conf"
grep -Fq 'select_installation_source' "${CORE_INSTALLER}" || fail "interactive installer does not offer source selection"
grep -Fq 'if ! pwd -P >/dev/null 2>&1' "${CLI}" || fail "dsm CLI cannot recover from a removed working directory"
grep -Fq -- '--local' "${CORE_INSTALLER}" || fail "local installation option is unavailable"
grep -Fq 'run mkdir -p "$(dirname "${DSM_LINK}")"' "${CORE_INSTALLER}" || fail "installer does not create custom CLI link parent"
grep -Fq 'guard_existing_installation' "${CORE_INSTALLER}" || fail "existing installation is not guarded"
grep -Fq 'initialize_database' "${CORE_INSTALLER}" || fail "installer does not initialize the database"
grep -Fq 'initialize_infrastructure_identity' "${CORE_INSTALLER}" || fail "installer does not bootstrap infrastructure identity"
grep -Fq 'bootstrap-profile' "${CORE_INSTALLER}" || fail "installer does not use Registry profile bootstrap"
grep -Fq 'initialize_runtime_state' "${CORE_INSTALLER}" || fail "installer does not initialize dashboard runtime state"
grep -Fq 'mkdir -p "${SYSTEMD_DIR}"' "${CORE_INSTALLER}" || fail "installer does not create a custom systemd unit directory"
grep -Fq -- '--reinstall' "${CORE_INSTALLER}" || fail "explicit reinstall option is unavailable"
grep -Fq 'legacy_worker_units=' "${CORE_INSTALLER}" || fail "installer does not disable duplicate legacy workers"
grep -Fq 'disable \' "${CORE_INSTALLER}" && grep -Fq -- '--now \' "${CORE_INSTALLER}" || fail "installer leaves legacy workers running"
python3 - "${CORE_INSTALLER}" <<'PY' || fail "profile bootstrap is not ordered after database initialization"
from pathlib import Path
import sys
text=Path(sys.argv[1]).read_text(encoding="utf-8"); main=text.split("main()",1)[1]
assert main.index("    initialize_database\n") < main.index("    initialize_infrastructure_identity\n") < main.index("    install_cli\n")
PY
TMP_DIR="$(mktemp -d)"; trap 'rm -rf -- "${TMP_DIR}"' EXIT
(
 id(){ case "$1" in -un) printf 'node1\n';; -gn) printf 'node1\n';; *) return 1;; esac; }; source "${CORE_INSTALLER}"; chown(){ :; }; chmod(){ :; }
 DSM_ROOT="${TMP_DIR}/opt/dsm"; DSM_SERVICE_USER="node1"; DSM_SERVICE_GROUP="node1"; DSM_SERVICE_HOME="/home/node1"; mkdir -p "${DSM_ROOT}/config"; cp "${ROOT}/config/dsm.conf" "${DSM_ROOT}/config/dsm.conf"; cp "${ROOT}/version" "${DSM_ROOT}/version"; printf 'LOCAL_SETTING="preserved"\n' >>"${DSM_ROOT}/config/dsm.conf"; normalize_database_settings; write_dsm_config >/dev/null
 grep -q '^DSM_USER="node1"$' "${DSM_ROOT}/config/dsm.conf" || fail "DSM_USER not written"; grep -q '^DSM_GROUP="node1"$' "${DSM_ROOT}/config/dsm.conf" || fail "DSM_GROUP not written"; grep -q '^DSM_HOME="/home/node1"$' "${DSM_ROOT}/config/dsm.conf" || fail "DSM_HOME not written"; grep -q "^DSM_VERSION=\"${EXPECTED_VERSION}\"$" "${DSM_ROOT}/config/dsm.conf" || fail "DSM_VERSION not written"; grep -q "^INSTALLER_VERSION=\"${EXPECTED_VERSION}\"$" "${DSM_ROOT}/config/dsm.conf" || fail "INSTALLER_VERSION not written"; grep -q "^DSM_DATABASE=\"${DSM_ROOT}/data/capivara.db\"$" "${DSM_ROOT}/config/dsm.conf" || fail "DSM_DATABASE not written"; grep -q '^DSM_DATABASE_DRIVER="sqlite"$' "${DSM_ROOT}/config/dsm.conf" || fail "database driver not written"; grep -q '^LOCAL_SETTING="preserved"$' "${DSM_ROOT}/config/dsm.conf" || fail "local setting overwritten"
)
(
 id(){ case "$1" in -un|-gn) printf 'capivara\n';; *) return 1;; esac; }; source "${CORE_INSTALLER}"; hostname(){ printf 'horizon-server\n'; }; chown(){ :; }; chmod(){ :; }; DSM_ROOT="${TMP_DIR}/agent-config-root"; DSM_NODE_ROLE="controller"; DSM_SERVICE_USER="capivara"; DSM_SERVICE_GROUP="capivara"; STEAMCMD_ROOT="${DSM_ROOT}/tools/steamcmd"; mkdir -p "${DSM_ROOT}/config"; printf 'DSM_NODE_ID=""\nDSM_NODE_ROLE=""\nAGENT_ID=""\n' >"${DSM_ROOT}/config/agent.conf"; write_agent_config; grep -q '^DSM_NODE_ID="horizon-server"$' "${DSM_ROOT}/config/agent.conf" || fail "reinstall did not repair the local Node identity"; grep -q '^DSM_NODE_ROLE="controller"$' "${DSM_ROOT}/config/agent.conf" || fail "reinstall did not repair the local Node role"; grep -q '^AGENT_ID=""$' "${DSM_ROOT}/config/agent.conf" || fail "Controller reinstall changed the Agent identity"
)
(
 id(){ case "$1" in -un) printf 'node1\n';; -gn) printf 'node1\n';; *) return 1;; esac; }; source "${CORE_INSTALLER}"; is_interactive(){ return 0; }; INSTALL_MODE="remote"; INSTALL_MODE_EXPLICIT=0; select_installation_source >/dev/null <<<"1"; [[ "${INSTALL_MODE}" == "local" ]] || fail "interactive local source was not selected"
)
if ( id(){ case "$1" in -un) printf 'node1\n';; -gn) printf 'node1\n';; *) return 1;; esac; }; source "${CORE_INSTALLER}"; DSM_ROOT="${TMP_DIR}/existing/opt/dsm"; DSM_SOURCE="${ROOT}"; ALLOW_REINSTALL=0; mkdir -p "${DSM_ROOT}/config"; printf '0.9.0\n' >"${DSM_ROOT}/version"; : >"${DSM_ROOT}/config/dsm.conf"; guard_existing_installation >/dev/null 2>&1 ); then fail "existing installation was overwritten without --reinstall"; fi
( id(){ case "$1" in -un) printf 'node1\n';; -gn) printf 'node1\n';; *) return 1;; esac; }; source "${CORE_INSTALLER}"; DSM_ROOT="${TMP_DIR}/existing/opt/dsm"; DSM_SOURCE="${ROOT}"; ALLOW_REINSTALL=1; guard_existing_installation >/dev/null 2>&1 )
(
 id(){ case "$1" in -un|-gn) printf 'node1\n';; *) return 1;; esac; }; source "${CORE_INSTALLER}"; DSM_ROOT="${TMP_DIR}/rendered-root"; SYSTEMD_DIR="${TMP_DIR}/rendered-systemd"; DSM_SERVICE_USER="node1"; DSM_SERVICE_GROUP="node1"; SYSTEMD_ACTIVE=1; mkdir -p "${DSM_ROOT}/systemd" "${SYSTEMD_DIR}"; cp "${ROOT}/systemd/dsm-dashboard.service" "${DSM_ROOT}/systemd/"; systemctl(){ :; }; install_systemd_units >/dev/null; rendered="${SYSTEMD_DIR}/dsm-dashboard.service"; grep -Fq "EnvironmentFile=-${DSM_ROOT}/config/dsm.conf" "${rendered}" || fail "dashboard service does not load the installed database configuration"; grep -Fq "${DSM_ROOT}/dashboard/server_part16.py" "${rendered}" || fail "rendered unit does not use configured DSM_ROOT"; ! grep -Fq '/opt/dsm' "${rendered}" || fail "rendered unit retains hard-coded /opt/dsm"
)
python3 -m unittest tests/profile_bootstrap_test.py
echo "Install manager tests passed."
