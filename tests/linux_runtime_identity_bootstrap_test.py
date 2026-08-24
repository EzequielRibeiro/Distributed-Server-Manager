from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_materializer_does_not_manage_system_accounts_or_agent_base_permissions():
    source = (ROOT / "agents/linux/privileged/materialize_instance.py").read_text(encoding="utf-8")
    assert "useradd" not in source
    assert "usermod" not in source
    assert "runtime user does not exist" in source
    assert "_grant_runtime_access" not in source
    assert "_validate_runtime_access" in source
    assert 'INSTANCE_STATE_BASE = Path("/var/lib/capivara-instances")' in source
    assert "_prepare_private_state" in source


def test_identity_bootstrap_owns_account_creation_home_and_base_permissions():
    source = (ROOT / "agents/linux/privileged/reconcile_runtime_identity.py").read_text(encoding="utf-8")
    assert 'RUNTIME_USER = "capivara-instance"' in source
    assert 'AGENT_GROUP = "capivara-agent"' in source
    assert 'RUNTIME_HOME = STATE_DIR / "runtime-home"' in source
    assert '"useradd"' in source
    assert '"usermod"' in source
    assert '"--home", runtime_home' in source
    assert "RUNTIME_HOME.mkdir" in source
    assert 'STATE_DIR / "game-data"' in source
    assert "os.chmod(STATE_DIR" in source
    assert "os.chmod(game_data" in source


def test_materializer_keeps_strict_filesystem_sandbox_with_explicit_instance_state_boundary():
    unit = (ROOT / "agents/linux/services/capivara-agent-materialize@.service").read_text(encoding="utf-8")
    assert "ProtectSystem=strict" in unit
    assert (
        "ReadWritePaths=/etc/systemd/system "
        "/var/lib/capivara-agent/privileged-materialization "
        "/var/lib/capivara-agent/game-data "
        "/var/lib/capivara-instances"
    ) in unit
    assert "ReadWritePaths=/etc " not in unit


def test_runtime_identity_has_dedicated_privileged_boundary():
    unit = (ROOT / "agents/linux/services/capivara-agent-runtime-identity.service").read_text(encoding="utf-8")
    assert "User=root" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/etc /var/lib/capivara-agent" in unit


def test_install_and_update_reconcile_identity_before_runtime_use():
    installer = (ROOT / "agents/linux/installer/install-agent.sh").read_text(encoding="utf-8")
    updater = (ROOT / "agents/linux/updater/updater.py").read_text(encoding="utf-8")
    assert "systemctl start capivara-agent-runtime-identity.service" in installer
    assert '"systemctl", "start", "capivara-agent-runtime-identity.service"' in updater


def test_agent_service_requires_runtime_identity_before_reconciliation_can_start():
    unit = (ROOT / "agents/linux/services/capivara-agent.service").read_text(encoding="utf-8")
    assert "Requires=capivara-agent-runtime-identity.service" in unit
    assert "After=network-online.target capivara-agent-runtime-identity.service" in unit
