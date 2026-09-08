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
usermod -a -G capivara-agent "${DSM_USER}" >/dev/null 2>&1 || true

install -d -m 0700 -o "${DSM_USER}" -g "${DSM_GROUP}" \
  "${DSM_ROOT}/runtime/hybrid-agent-state" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/instance-provisioning" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/instance-provisioning/history" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/instance-workspaces" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/privileged-materialization" \
  "${DSM_ROOT}/runtime/hybrid-agent-state/privileged-backup-restore"

install -d -m 0711 -o root -g root "${DSM_ROOT}/runtime/hybrid-instance-storage"

materializer_template="${DSM_ROOT}/systemd/dsm-hybrid-agent-materialize@.service.in"
files_access_template="${DSM_ROOT}/systemd/dsm-hybrid-agent-files-access@.service.in"
backup_restore_template="${DSM_ROOT}/systemd/dsm-hybrid-agent-backup-restore@.service.in"
[[ -f "${materializer_template}" ]] || { echo "[ERRO] template ausente: ${materializer_template}" >&2; exit 1; }
[[ -f "${files_access_template}" ]] || { echo "[ERRO] template ausente: ${files_access_template}" >&2; exit 1; }
[[ -f "${backup_restore_template}" ]] || { echo "[ERRO] template ausente: ${backup_restore_template}" >&2; exit 1; }

sed \
  -e "s|@DSM_ROOT@|${DSM_ROOT}|g" \
  -e "s|@DSM_USER@|${DSM_USER}|g" \
  "${materializer_template}" > /etc/systemd/system/dsm-hybrid-agent-materialize@.service
chmod 0644 /etc/systemd/system/dsm-hybrid-agent-materialize@.service

sed \
  -e "s|@DSM_ROOT@|${DSM_ROOT}|g" \
  "${files_access_template}" > /etc/systemd/system/dsm-hybrid-agent-files-access@.service
chmod 0644 /etc/systemd/system/dsm-hybrid-agent-files-access@.service

sed \
  -e "s|@DSM_ROOT@|${DSM_ROOT}|g" \
  -e "s|@DSM_USER@|${DSM_USER}|g" \
  "${backup_restore_template}" > /etc/systemd/system/dsm-hybrid-agent-backup-restore@.service
chmod 0644 /etc/systemd/system/dsm-hybrid-agent-backup-restore@.service

install -d -m 0755 /etc/systemd/system/dsm-dashboard-worker.service.d
cat > /etc/systemd/system/dsm-dashboard-worker.service.d/40-hybrid-backup-restore.conf <<EOF
[Service]
Environment=CAPIVARA_BACKUP_RESTORE_UNIT_TEMPLATE=dsm-hybrid-agent-backup-restore@{command_id}.service
EOF
chmod 0644 /etc/systemd/system/dsm-dashboard-worker.service.d/40-hybrid-backup-restore.conf

if command -v pkaction >/dev/null 2>&1 || [[ -d /etc/polkit-1/rules.d ]]; then
  install -d -m 0755 /etc/polkit-1/rules.d
  cat > /etc/polkit-1/rules.d/49-capivara-hybrid-materializer.rules <<EOF
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == "${DSM_USER}") {
        var unit = action.lookup("unit");
        var instanceUnit = /^capivara-instance-[A-Za-z0-9._-]{1,191}\\.service$/;
        if (unit && (
            unit.indexOf("dsm-hybrid-agent-materialize@") === 0 ||
            unit.indexOf("dsm-hybrid-agent-files-access@") === 0 ||
            unit.indexOf("dsm-hybrid-agent-backup-restore@") === 0 ||
            instanceUnit.test(unit)
        )) {
            return polkit.Result.YES;
        }
    }
});
EOF
  chmod 0644 /etc/polkit-1/rules.d/49-capivara-hybrid-materializer.rules
fi

systemctl daemon-reload
echo "[OK] Hybrid privileged runtime substrate instalado."
