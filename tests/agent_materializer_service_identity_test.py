from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "agents" / "linux" / "services" / "capivara-agent-materialize@.service"


def test_materializer_service_allows_runtime_identity_reconciliation_without_full_system_write_access():
    content = SERVICE.read_text(encoding="utf-8")

    assert "User=root\n" in content
    assert "Group=root\n" in content
    assert "ProtectSystem=full\n" in content
    assert "ProtectSystem=strict\n" not in content
    assert (
        "ReadWritePaths=/etc/systemd/system "
        "/var/lib/capivara-agent/privileged-materialization "
        "/var/lib/capivara-agent/game-data\n"
        in content
    )
    assert "ProtectHome=true\n" in content
    assert "NoNewPrivileges=true\n" in content
