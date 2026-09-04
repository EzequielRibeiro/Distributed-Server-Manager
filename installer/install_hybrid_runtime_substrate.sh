#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
CONFIG="${DSM_ROOT}/config/dsm.conf"
[[ ${EUID} -eq 0 ]] || { echo "[ERRO] execute como root" >&2; exit 1; }
[[ -f "${CONFIG}" ]] || { echo "[ERRO] config ausente: ${CONFIG}" >&2; exit 1; }

DSM_USER="$(sed -n 's/^DSM_USER="\([^"]*\)"$/\1/p' "${CONFIG}" | tail -n1)"
DSM_GROUP="$(sed -n 's/^DSM_GROUP="\([^"]*\)"$/\1/p' "${CONFIG}" | tail -n1)"
DSM_USER="${DSM_USER:-capivara}"
DSM_GROUP="${DSM_GROUP:-capivara}"

getent group capivara-agent >/dev/null 2>&1 || groupadd --system capivara-agent
id capivara-instance >/dev/null 2>&1 || useradd --system --gid capivara-agent --home /nonexistent --shell /usr/sbin/nologin capivara-instance
usermod -a -G capivara-agent capivara-instance >/dev/null 2>&1 || true

install -d -m 0700 -o "${DSM_USER}" -g "${DSM_GROUP}" \
  "${DSM_ROOT}/runtime/hybrid-agent-state" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/instance-provisioning" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/instance-provisioning/history" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/instance-workspaces" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/privileged-materialization"

install -d -m 0711 -o root -g root "${DSM_ROOT}/runtime/hybrid-instance-storage"

template="${DSM_ROOT}/systemd/dsm-hybrid-agent-materialize@.service.in"
[[ -f "${template}" ]] || { echo "[ERRO] template ausente: ${template}" >&2; exit 1; }

sed \
  -e "s|@DSM_ROOT@|${DSM_ROOT}|g" \
  -e "s|@DSM_USER@|${DSM_USER}|g" \
  "${template}" > /etc/systemd/system/dsm-hybrid-agent-materialize@.service
chmod 0644 /etc/systemd/system/dsm-hybrid-agent-materialize@.service

if command -v pkaction >/dev/null 2>&1 || [[ -d /etc/polkit-1/rules.d ]]; then
  install -d -m 0755 /etc/polkit-1/rules.d
  cat > /etc/polkit-1/rules.d/49-capivara-hybrid-materializer.rules <<EOF
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == "${DSM_USER}") {
        var unit = action.lookup("unit");
        if (unit && unit.indexOf("dsm-hybrid-agent-materialize@") === 0) {
            return polkit.Result.YES;
        }
    }
});
EOF
  chmod 0644 /etc/polkit-1/rules.d/49-capivara-hybrid-materializer.rules
fi

systemctl daemon-reload
echo "[OK] Hybrid privileged runtime substrate instalado."
