#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release" / "readiness-v2.json"
VERSION_FILE = ROOT / "version"


def main():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = VERSION_FILE.read_text(encoding="utf-8").strip()

    assert data["schema_version"] == 1
    assert data["release_line"] == "2.0"
    assert data["release_version"] == version
    assert data["tag_name"] == f"v{version}"
    assert data["publish_release"] is False
    assert data["release_authorized"] is True

    notes = ROOT / "release" / f"RELEASE_NOTES_{version}.md"
    assert notes.is_file(), f"missing release notes for {version}"
    notes_text = notes.read_text(encoding="utf-8")
    assert f"Capivara DSM {version}" in notes_text

    gates = set(data["required_gates"])
    required = {
        "CI",
        "Agent Instance Runtime",
        "Agent Game Data",
        "Agent Local CLI",
        "Agent SSH Deploy",
        "Dashboard Remote Agent Install",
        "Windows Agent Parity",
        "Agent public network",
        "Controller TLS Transport",
        "External Controller Agent E2E",
        "Final Customer Distributed E2E",
        "Customer Instance Workspace v2",
        "Customer Workspace Functional Deployment",
        "Customer Geographic Placement",
        "Customer Health Alerting",
        "Universal Event Platform",
        "Universal Configuration Platform",
        "Universal Observability Platform",
        "Universal Content Platform",
        "Universal Smart Backup",
        "Automation and Universal Broadcast",
        "Real-Time API Platform",
        "Multi-Datacenter Federation",
        "High Availability and Disaster Recovery",
        "P8 Administrative Observability",
        "PostgreSQL Baseline v2 Isolated Deployment",
        "Legacy Audit",
        "Capivara 2.0 Release Readiness",
    }
    assert required <= gates

    capabilities = set(data["mandatory_capabilities"])
    for capability in {
        "windows-agent-parity",
        "controller-tls",
        "external-controller-agent-e2e",
        "customer-distributed-e2e",
        "agent-public-network",
        "customer-public-connection-address",
        "administrative-observability",
    }:
        assert capability in capabilities

    inv = data["release_invariants"]
    assert inv["game_agnostic_core"] is True
    assert inv["active_installation_mutation"] is False
    assert inv["automatic_release_publication"] is False
    assert inv["release_tag_matches_project_version"] is True
    assert inv["release_notes_required"] is True
    assert set(inv["database_schema_parity"]) == {"sqlite", "postgresql", "mysql-mariadb"}

    doc = (ROOT / "docs" / "architecture" / "e3-final-consolidation-release-readiness.md").read_text(encoding="utf-8")
    for phrase in (
        "Upgrade and migration readiness",
        "Security hardening",
        "Reliability and scale",
        "Release candidate gate",
    ):
        assert phrase in doc

    print(f"P9 release readiness contract: OK ({version})")


if __name__ == "__main__":
    main()
