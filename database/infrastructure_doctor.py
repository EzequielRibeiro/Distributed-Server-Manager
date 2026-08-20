#!/usr/bin/env python3
"""Infrastructure recovery diagnostics and conservative reconciliation.

Phase 20 intentionally separates detection from mutation. The doctor can refresh
runtime health from heartbeat age, but never reassigns Agents, locations or
instances automatically.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from typing import Any

from agent_port_availability import effective_port_summary
from agent_runtime_repository import AgentRuntimeRepository
from alert_repository import AlertSession
from placement_status_repository import PlacementStatusRepository
from runtime_backend import backend_from_environment


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    component: str
    message: str
    subject_id: str | None = None
    repairable: bool = False
    recommendation: str | None = None


class InfrastructureDoctor:
    def __init__(self, backend):
        self.backend = backend

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return [dict(row) for row in session.execute(sql, params).fetchall()]
            finally:
                session.close()

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def reconcile_safe(self) -> list[dict[str, Any]]:
        """Apply only deterministic repairs derived from existing facts."""
        runtime = AgentRuntimeRepository(self.backend)
        before = {
            row["agent_id"]: row["health_status"]
            for row in self._rows("SELECT agent_id,health_status FROM agent_runtime_inventory")
        }
        refreshed = runtime.refresh_health()
        actions = []
        for agent_id, health in refreshed.items():
            previous = before.get(agent_id)
            if previous is not None and previous != health:
                actions.append({
                    "action": "refresh_agent_health",
                    "agent_id": agent_id,
                    "from": previous,
                    "to": health,
                })
        return actions

    def diagnose(self, *, reconcile: bool = False) -> dict[str, Any]:
        self.backend.initialize()
        repairs = self.reconcile_safe() if reconcile else []
        if not reconcile:
            # Read-time health still needs to reflect heartbeat age, but this is
            # the same deterministic reconciliation used by placement reads.
            AgentRuntimeRepository(self.backend).refresh_health()

        findings: list[Finding] = []

        controllers = self._rows(
            "SELECT c.id,c.status,c.node_id,n.id AS node_exists,n.role AS node_role "
            "FROM controllers c LEFT JOIN nodes n ON n.id=c.node_id ORDER BY c.id"
        )
        active_controllers = [row for row in controllers if str(row["status"]).lower() == "active"]
        if not active_controllers:
            findings.append(Finding(
                "no_active_controller", "critical", "controller",
                "Nenhum Controller ativo está disponível.",
                recommendation="Restaurar ou ativar um Controller válido.",
            ))
        for row in controllers:
            if row["node_exists"] is None:
                findings.append(Finding(
                    "controller_orphan_node", "critical", "controller",
                    "Controller referencia Node inexistente.", str(row["id"]),
                    recommendation="Restaurar o Node correspondente; não recriar identidade por adivinhação.",
                ))
            elif str(row["node_role"]).lower() not in {"controller", "hybrid"}:
                findings.append(Finding(
                    "controller_node_role_mismatch", "critical", "controller",
                    "Role do Node não é compatível com Controller.", str(row["id"]),
                    recommendation="Corrigir a identidade de infraestrutura após validar o host.",
                ))

        agents = self._rows(
            "SELECT a.id,a.controller_id,a.node_id,a.status,n.id AS node_exists,c.id AS controller_exists,"
            "ari.health_status,ari.last_seen,ari.address,ari.hostname,ari.fingerprint "
            "FROM agents a LEFT JOIN nodes n ON n.id=a.node_id "
            "LEFT JOIN controllers c ON c.id=a.controller_id "
            "LEFT JOIN agent_runtime_inventory ari ON ari.agent_id=a.id ORDER BY a.id"
        )
        active_agents = [row for row in agents if str(row["status"]).lower() == "active"]
        online_agents = [row for row in active_agents if str(row.get("health_status") or "offline").lower() == "online"]

        for row in agents:
            agent_id = str(row["id"])
            if row["node_exists"] is None or row["controller_exists"] is None:
                findings.append(Finding(
                    "agent_orphan", "critical", "agents",
                    "Agent perdeu sua cadeia Controller/Node.", agent_id,
                    recommendation="Restaurar a referência ausente antes de qualquer novo placement.",
                ))
            if str(row["status"]).lower() == "active" and row["last_seen"] is None:
                findings.append(Finding(
                    "agent_never_seen", "warning", "agents",
                    "Agent ativo ainda não registrou heartbeat.", agent_id,
                    recommendation="Verificar instalação, configuração local e credencial permanente.",
                ))
            elif str(row["status"]).lower() == "active" and str(row.get("health_status") or "offline").lower() != "online":
                findings.append(Finding(
                    "agent_unreachable", "warning", "agents",
                    f"Agent ativo está {row.get('health_status') or 'offline'}.", agent_id,
                    recommendation="Verificar conectividade; mudança de IP é aceita no próximo heartbeat autenticado.",
                ))

        credential_rows = self._rows(
            "SELECT a.id AS agent_id,COUNT(ac.id) AS active_credentials "
            "FROM agents a LEFT JOIN agent_credentials ac ON ac.agent_id=a.id AND ac.status='active' "
            "GROUP BY a.id ORDER BY a.id"
        )
        for row in credential_rows:
            if int(row["active_credentials"] or 0) == 0:
                findings.append(Finding(
                    "agent_missing_credential", "critical", "agents",
                    "Agent não possui credencial permanente ativa.", str(row["agent_id"]),
                    recommendation="Executar novo pareamento controlado; não emitir segredo automaticamente.",
                ))

        duplicate_fingerprints = self._rows(
            "SELECT fingerprint,COUNT(DISTINCT agent_id) AS total "
            "FROM agent_runtime_inventory WHERE fingerprint IS NOT NULL AND fingerprint<>'' "
            "GROUP BY fingerprint HAVING COUNT(DISTINCT agent_id)>1"
        )
        for row in duplicate_fingerprints:
            members = self._rows(
                "SELECT agent_id,hostname,address,health_status FROM agent_runtime_inventory "
                "WHERE fingerprint=? ORDER BY agent_id" if self.backend.name == "sqlite" else
                "SELECT agent_id,hostname,address,health_status FROM agent_runtime_inventory "
                "WHERE fingerprint=%s ORDER BY agent_id",
                (row["fingerprint"],),
            )
            findings.append(Finding(
                "duplicate_agent_identity", "critical", "agents",
                "Mais de um Agent reporta a mesma fingerprint: " + ", ".join(str(item["agent_id"]) for item in members),
                recommendation="Escolher administrativamente a identidade válida e revogar a duplicada.",
            ))

        locations = self._rows(
            "SELECT a.id AS agent_id,a.status AS agent_status,al.datacenter_id,al.status AS location_status,"
            "d.id AS datacenter_exists,d.status AS datacenter_status,d.region_id,"
            "r.id AS region_exists,r.status AS region_status "
            "FROM agents a LEFT JOIN agent_locations al ON al.agent_id=a.id "
            "LEFT JOIN datacenters d ON d.id=al.datacenter_id "
            "LEFT JOIN regions r ON r.id=d.region_id ORDER BY a.id"
        )
        for row in locations:
            agent_id = str(row["agent_id"])
            if row["datacenter_id"] is None:
                if str(row["agent_status"]).lower() == "active":
                    findings.append(Finding(
                        "missing_agent_location", "critical", "locations",
                        "Agent ativo não possui localização.", agent_id,
                        recommendation="Selecionar Region/Datacenter explicitamente no Dashboard.",
                    ))
                continue
            if row["datacenter_exists"] is None:
                findings.append(Finding(
                    "orphan_agent_location", "critical", "locations",
                    "Localização referencia Datacenter inexistente.", agent_id,
                    recommendation="Restaurar o Datacenter ou mover o Agent explicitamente; instâncias devem permanecer intactas.",
                ))
                continue
            if row["region_exists"] is None:
                findings.append(Finding(
                    "orphan_datacenter_region", "critical", "datacenters",
                    "Datacenter referencia Region inexistente.", str(row["datacenter_id"]),
                    recommendation="Restaurar a Region correta antes de reativar placement.",
                ))
            if str(row.get("datacenter_status") or "").lower() != "active":
                findings.append(Finding(
                    "datacenter_disabled_for_agent", "warning", "datacenters",
                    "Agent está associado a Datacenter desabilitado.", agent_id,
                    recommendation="Reativar o Datacenter ou mover o Agent de forma administrativa.",
                ))
            if str(row.get("region_status") or "").lower() != "active":
                findings.append(Finding(
                    "region_disabled_for_agent", "warning", "regions",
                    "Agent está associado a Region desabilitada.", agent_id,
                    recommendation="Reativar a Region ou mover o Datacenter/Agent explicitamente.",
                ))

        port_conflicts = 0
        agents_without_ranges = 0
        for row in active_agents:
            agent_id = str(row["id"])
            summary = effective_port_summary(self.backend, agent_id)
            ranges = list(summary.get("ranges") or [])
            if not ranges:
                agents_without_ranges += 1
                findings.append(Finding(
                    "agent_without_port_range", "warning", "port_allocation",
                    "Agent ativo não possui faixa administrada de portas.", agent_id,
                    recommendation="Configurar TCP/UDP conforme os runtimes que este Agent deverá hospedar.",
                ))
            conflicts = int(summary.get("conflict_count") or summary.get("observed_conflict_count") or 0)
            if conflicts:
                port_conflicts += conflicts
                findings.append(Finding(
                    "port_conflict", "critical", "port_allocation",
                    f"Foram encontrados {conflicts} conflito(s) de porta.", agent_id,
                    recommendation="Resolver reservas/sockets conflitantes antes de novo placement.",
                ))

        placement = PlacementStatusRepository(self.backend).snapshot()
        placement_ready = bool(placement.get("placement_ready"))
        if not placement_ready:
            findings.append(Finding(
                "placement_not_ready", "critical", "placement",
                "Infraestrutura não possui Agent elegível para placement.",
                recommendation="Corrigir os blockers reportados antes de provisionar novas instâncias.",
            ))

        region_counts = self._one(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active FROM regions"
        ) or {"total": 0, "active": 0}
        dc_counts = self._one(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active FROM datacenters"
        ) or {"total": 0, "active": 0}
        located_active = sum(1 for row in locations if str(row["agent_status"]).lower() == "active" and row["datacenter_id"] is not None)

        def component_status(component: str, *, warning_is_ok: bool = False) -> str:
            relevant = [item for item in findings if item.component == component]
            if any(item.severity == "critical" for item in relevant):
                return "ERROR"
            if any(item.severity == "warning" for item in relevant):
                return "OK" if warning_is_ok else "WARN"
            return "OK"

        summary = [
            {"label": "Controller", "status": component_status("controller"), "detail": f"{len(active_controllers)}/{len(controllers)} active"},
            {"label": "Agents", "status": component_status("agents"), "detail": f"{len(online_agents)}/{len(active_agents)} online"},
            {"label": "Locations", "status": component_status("locations"), "detail": f"{located_active}/{len(active_agents)} active located"},
            {"label": "Regions", "status": component_status("regions"), "detail": f"{int(region_counts.get('active') or 0)}/{int(region_counts.get('total') or 0)} active"},
            {"label": "Datacenters", "status": component_status("datacenters"), "detail": f"{int(dc_counts.get('active') or 0)}/{int(dc_counts.get('total') or 0)} active"},
            {"label": "Port allocation", "status": component_status("port_allocation"), "detail": f"conflicts={port_conflicts}, without_ranges={agents_without_ranges}"},
            {"label": "Placement", "status": "READY" if placement_ready else "NOT READY", "detail": f"eligible_agents={placement.get('eligible_agents', 0)}"},
        ]

        ready = placement_ready and not any(item.severity == "critical" for item in findings)
        return {
            "schema_version": 1,
            "kind": "CapivaraInfrastructureDoctor",
            "ready": ready,
            "reconcile_mode": bool(reconcile),
            "repairs": repairs,
            "summary": summary,
            "findings": [asdict(item) for item in findings],
            "placement": placement,
        }


def _print_human(payload: dict[str, Any]) -> None:
    for item in payload["summary"]:
        print(f"{item['label']:<20} {item['status']:<10} {item['detail']}")
    if payload["repairs"]:
        print("\nReconciliação segura:")
        for action in payload["repairs"]:
            print(f"- {action['agent_id']}: health {action['from']} -> {action['to']}")
    if payload["findings"]:
        print("\nAchados:")
        for finding in payload["findings"]:
            subject = f" [{finding['subject_id']}]" if finding.get("subject_id") else ""
            print(f"- {finding['severity'].upper()} {finding['code']}{subject}: {finding['message']}")
            if finding.get("recommendation"):
                print(f"  Ação: {finding['recommendation']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capivara infrastructure doctor")
    parser.add_argument("command", nargs="?", default="doctor", choices=("doctor",))
    parser.add_argument("--reconcile", action="store_true", help="aplica somente reconciliações determinísticas e seguras")
    parser.add_argument("--json", action="store_true", help="saída estruturada")
    args = parser.parse_args(argv)

    backend = backend_from_environment()
    try:
        payload = InfrastructureDoctor(backend).diagnose(reconcile=args.reconcile)
    finally:
        backend.close()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_human(payload)
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
