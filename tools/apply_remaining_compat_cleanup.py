#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def remove_between(text: str, start: str, end: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_index] + text[end_index:]


def update_dashboard_server() -> None:
    path = ROOT / "dashboard" / "server.py"
    text = path.read_text(encoding="utf-8")

    state_block = '''# =============================================================
# Dashboard State
# =============================================================
STATE_FILES = {
    "dashboard": STATE_DIR / "dashboard_state.json",
    "server": STATE_DIR / "server_state.json",
    "metrics": STATE_DIR / "metrics_state.json",
    "monitor": STATE_DIR / "monitor_state.json",
    "alerts": STATE_DIR / "alerts_state.json",
    "scheduler": STATE_DIR / "scheduler_state.json",
    "events": STATE_DIR / "events_state.json",
}

'''
    text = replace_once(text, state_block, "", "dashboard state-file registry")

    for route_line in (
        '    "monitor": "monitor.sh",\n',
        '    "metrics": "metrics.sh",\n',
        '    "health": "health.sh",\n',
    ):
        text = replace_once(text, route_line, "", f"retired API route {route_line.strip()}")

    text = remove_between(
        text,
        "# =============================================================\n# Dashboard State Engine\n# =============================================================\n",
        "def api_mods_real():",
        "dashboard JSON state engine",
    )

    text = remove_between(
        text,
        "def api_events_real():",
        "def api_current_operation():",
        "legacy events projection endpoint",
    )

    health_block = '''def dashboard_health():
    """Return fail-closed Controller health from the authoritative database backend."""
    generated_at = int(time.time())
    try:
        result = dashboard_repository(DATABASE_FILE).backend.health_check()
        database = dict(result) if isinstance(result, dict) else {}
        reported = str(
            database.get("status")
            or database.get("health")
            or ""
        ).strip().lower()
        connected = database.get("connected")
        if connected is None:
            connected = reported in {"ok", "healthy", "online", "ready"}
        healthy = bool(connected) and reported not in {
            "error", "failed", "critical", "offline", "missing", "unhealthy"
        }
        safe_database = {
            key: database[key]
            for key in ("driver", "status", "health", "connected")
            if key in database
        }
        safe_database["connected"] = bool(connected)
        return {
            "score": 100 if healthy else 0,
            "status": "healthy" if healthy else "critical",
            "components": {"database": safe_database},
            "generated_at": generated_at,
        }
    except Exception:
        return {
            "score": 0,
            "status": "critical",
            "components": {"database": {"connected": False}},
            "generated_at": generated_at,
        }


'''
    text = remove_between(
        text,
        "def api_logs():",
        "# =============================================================\n# Execução de Scripts API | API Scripts Execution\n# =============================================================\n",
        "legacy logs/summary/health projections",
    )
    exec_marker = "# =============================================================\n# Execução de Scripts API | API Scripts Execution\n# =============================================================\n"
    text = replace_once(text, exec_marker, health_block + exec_marker, "database-backed dashboard health")

    text = replace_once(
        text,
        '        if path == "/health":\n            self.send_json(200, dashboard_health())\n            return\n',
        '        if path == "/health":\n            health = dashboard_health()\n            self.send_json(200 if health.get("status") == "healthy" else 503, health)\n            return\n',
        "public health HTTP status",
    )

    for endpoint_line in (
        '            "/api/server": api_server_real,\n',
        '            "/api/resources": api_resources_real,\n',
        '            "/api/events": api_events_real,\n',
        '            "/api/logs": api_logs,\n',
        '            "/api/dashboard/summary": dashboard_summary,\n',
    ):
        text = replace_once(text, endpoint_line, "", f"retired endpoint {endpoint_line.strip()}")

    if "STATE_FILES" in text or "DashboardState" in text or "dashboard_state.json" in text:
        raise RuntimeError("dashboard legacy state engine residue remains")
    path.write_text(text, encoding="utf-8")


def update_updater() -> None:
    path = ROOT / "update.sh"
    text = path.read_text(encoding="utf-8")

    text = replace_once(text, 'BIN_LINK="/usr/local/bin/dsm"\n', "", "public dsm link")

    text = remove_between(
        text,
        "# =============================================================\n# Migração de conta de runtime para instalações legadas\n# Legacy runtime account migration\n# =============================================================\n",
        "# =============================================================\n# Carregar configuração DSM existente\n# Load existing DSM configuration\n# =============================================================\n",
        "legacy runtime-account inference",
    )
    text = replace_once(text, "\n    resolve_legacy_runtime_account\n", "\n", "legacy runtime-account call")

    for required in (
        '        "bin/dsm"\n',
        '        "bin/dsm"\n',
    ):
        if required not in text:
            raise RuntimeError("expected bin/dsm requirement not found")
        text = text.replace(required, "", 1)

    text = replace_once(text, '    chmod +x "${INSTALL_DIR}/bin/dsm"\n', "", "bin/dsm chmod")

    text = remove_between(
        text,
        "# =============================================================\n# Criar links globais DSM/Capivara | Create global DSM/Capivara links\n# =============================================================\n",
        "# =============================================================\n# Atualizar e reconciliar serviços Systemd | Update Systemd services\n# =============================================================\n",
        "legacy command links",
    )
    cap_command = '''# =============================================================
# Instalar comando global Capivara | Install global Capivara command
# =============================================================
install_command() {
    echo
    echo "Atualizando comando global Capivara..."
    echo "Updating global Capivara command."

    ln -sf "${INSTALL_DIR}/bin/cap" "${CAP_LINK}"
    chmod +x "${CAP_LINK}"

    # `cap` is the only public CLI. Remove any obsolete public dsm alias.
    rm -f -- /usr/local/bin/dsm

    echo "Comando Capivara atualizado | Capivara command updated."
}

'''
    systemd_marker = "# =============================================================\n# Atualizar e reconciliar serviços Systemd | Update Systemd services\n# =============================================================\n"
    text = replace_once(text, systemd_marker, cap_command + systemd_marker, "cap-only global command")

    text = remove_between(
        text,
        "# =============================================================\n# Reconciliar substrato privilegiado Hybrid durante upgrade\n# Reconcile privileged Hybrid substrate during upgrade\n# =============================================================\n",
        "# =============================================================\n# Migrar workers legados do Dashboard | Migrate legacy Dashboard workers\n# =============================================================\n",
        "hybrid legacy compatibility and dashboard worker migration",
    )
    hybrid = '''# =============================================================
# Reconciliar substrato privilegiado Hybrid durante upgrade
# Reconcile privileged Hybrid substrate during upgrade
# =============================================================
reconcile_hybrid_runtime_substrate() {
    local INSTALLER="${INSTALL_DIR}/installer/install_hybrid_runtime_substrate.sh"
    local AGENT_CONFIG="${INSTALL_DIR}/runtime/hybrid-agent-state/agent.json"

    if [[ "${SYSTEMD_ENABLED}" -ne 1 ]]
    then
        echo "Substrato Hybrid ignorado: systemd desativado."
        return 0
    fi

    # The persisted embedded-Agent config is the only supported Hybrid marker.
    if [[ ! -f "${AGENT_CONFIG}" ]]
    then
        echo "Substrato Hybrid não aplicável a esta instalação."
        return 0
    fi

    if [[ ! -f "${INSTALLER}" ]]
    then
        echo "[ERROR] Instalador do substrato Hybrid ausente: ${INSTALLER}" >&2
        return 1
    fi

    DSM_ROOT="${INSTALL_DIR}" bash "${INSTALLER}"
}

'''
    migration_marker = "# =============================================================\n# Migrar workers legados do Dashboard | Migrate legacy Dashboard workers\n# =============================================================\n"
    text = replace_once(text, migration_marker, hybrid + migration_marker, "canonical hybrid reconciliation")
    text = remove_between(
        text,
        migration_marker,
        "# =============================================================\n# Reiniciar serviços DSM | Restart DSM services\n# =============================================================\n",
        "legacy dashboard worker service migration",
    )
    text = replace_once(text, "\n    migrate_dashboard_worker_services\n", "\n", "legacy worker migration call")

    fallback_pattern = re.compile(
        r'\n        # Compatibility fallback for installations created before DSM_WEB_PORT.*?dashboard\.conf"\)\n        fi\n',
        re.S,
    )
    text, count = fallback_pattern.subn("\n", text, count=1)
    if count != 1:
        raise RuntimeError(f"dashboard port compatibility fallback: expected 1 match, got {count}")

    text = remove_between(
        text,
        "# =============================================================\n# Executar Doctor DSM | Run DSM Doctor\n# =============================================================\n",
        "# =============================================================\n# Check Internet\n# =============================================================\n",
        "legacy dsm doctor execution",
    )
    text = replace_once(text, "\n    run_doctor\n", "\n", "legacy doctor call")

    rollback_start = "    # Reconcile privileged Hybrid substrate from the restored package.\n"
    rollback_end = "    # Atualizar Systemd | Update Systemd\n"
    canonical_rollback = '''    # Reconcile privileged Hybrid substrate from the restored package.
    if [[ "${SYSTEMD_ENABLED}" -eq 1 ]]
    then
        local RESTORED_HYBRID_INSTALLER="${INSTALL_DIR}/installer/install_hybrid_runtime_substrate.sh"
        local RESTORED_HYBRID_CONFIG="${INSTALL_DIR}/runtime/hybrid-agent-state/agent.json"

        if [[ -f "${RESTORED_HYBRID_CONFIG}" ]]
        then
            [[ -f "${RESTORED_HYBRID_INSTALLER}" ]] || {
                echo "Restored Hybrid installation is missing its substrate installer." >&2
                return 1
            }
            DSM_ROOT="${INSTALL_DIR}" bash "${RESTORED_HYBRID_INSTALLER}" || return 1
        fi
    fi
'''
    start = text.find(rollback_start)
    end = text.find(rollback_end, start)
    if start < 0 or end < 0:
        raise RuntimeError("rollback Hybrid compatibility block not found")
    text = text[:start] + canonical_rollback + text[end:]

    for residue in (
        "resolve_legacy_runtime_account",
        "migrate_dashboard_worker_services",
        "LEGACY_MATERIALIZER",
        "RESTORED_MATERIALIZER",
        'BIN_LINK="/usr/local/bin/dsm"',
        "Compatibility fallback for installations created before DSM_WEB_PORT",
        "mantendo estado compatível legado",
        "preserving legacy-compatible state",
    ):
        if residue in text:
            raise RuntimeError(f"updater compatibility residue remains: {residue}")

    path.write_text(text, encoding="utf-8")


def update_legacy_audit() -> None:
    path = ROOT / "tools" / "legacy_audit.py"
    text = path.read_text(encoding="utf-8")
    anchor = '    "dashboard/workers/monitor_worker.sh",\n'
    additions = (
        '    "dashboard/api/metrics.sh",\n'
        '    "dashboard/api/monitor.sh",\n'
        '    "dashboard/api/health.sh",\n'
        '    "bin/dsm",\n'
    )
    text = replace_once(text, anchor, anchor + additions, "new retired paths")
    text = replace_once(
        text,
        'DOCUMENTED_COMPATIBILITY = {\n    "update.sh",\n}\n',
        'DOCUMENTED_COMPATIBILITY = set()\n',
        "zero documented compatibility surfaces",
    )
    path.write_text(text, encoding="utf-8")


def remove_retired_files() -> None:
    for relative in (
        "dashboard/api/metrics.sh",
        "dashboard/api/monitor.sh",
        "dashboard/api/health.sh",
        "bin/dsm",
    ):
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"expected retired file not found: {relative}")
        path.unlink()


def main() -> None:
    update_dashboard_server()
    update_updater()
    update_legacy_audit()
    remove_retired_files()
    print("remaining compatibility cleanup applied")


if __name__ == "__main__":
    main()
