#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release" / "readiness-v2.json"


def main():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["release_line"] == "2.0"
    assert data["publish_release"] is False
    gates = set(data["required_gates"])
    required = {
        "CI", "Universal Event Platform", "Universal Configuration Platform",
        "Universal Observability Platform", "Universal Content Platform",
        "Universal Smart Backup", "Automation and Universal Broadcast",
        "Real-Time API Platform", "Multi-Datacenter Federation",
        "High Availability and Disaster Recovery", "Capivara 2.0 Release Readiness"
    }
    assert required <= gates
    inv = data["release_invariants"]
    assert inv["game_agnostic_core"] is True
    assert inv["active_installation_mutation"] is False
    assert inv["automatic_release_publication"] is False
    assert set(inv["database_migration_parity"]) == {"sqlite", "postgresql", "mysql-mariadb"}
    doc = (ROOT / "docs" / "architecture" / "e3-final-consolidation-release-readiness.md").read_text(encoding="utf-8")
    for phrase in ("Upgrade and migration readiness", "Security hardening", "Reliability and scale", "Release candidate gate"):
        assert phrase in doc
    print("E3 release readiness contract: OK")


if __name__ == "__main__":
    main()
