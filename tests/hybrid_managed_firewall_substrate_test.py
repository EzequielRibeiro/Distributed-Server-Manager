from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hybrid_substrate_installs_managed_firewall_contract():
    installer = (
        ROOT / "installer" / "install_hybrid_runtime_substrate.sh"
    ).read_text(encoding="utf-8")

    assert (
        '"${DSM_ROOT}/runtime/hybrid-agent-state/privileged-firewall"'
        in installer
    )
    assert (
        'firewall_template="${DSM_ROOT}/systemd/'
        'dsm-hybrid-agent-firewall@.service.in"'
        in installer
    )
    assert (
        '"${firewall_template}" > '
        '/etc/systemd/system/dsm-hybrid-agent-firewall@.service'
        in installer
    )
    assert (
        'unit.indexOf("dsm-hybrid-agent-firewall@") === 0'
        in installer
    )


def test_hybrid_firewall_unit_uses_hybrid_state_and_root_helper():
    unit = (
        ROOT / "systemd" / "dsm-hybrid-agent-firewall@.service.in"
    ).read_text(encoding="utf-8")

    assert "User=root" in unit
    assert "Group=root" in unit
    assert (
        "Environment=CAPIVARA_AGENT_STATE_DIR="
        "@DSM_ROOT@/runtime/hybrid-agent-state"
        in unit
    )
    assert (
        "ExecStart=/usr/bin/python3 "
        "@DSM_ROOT@/agents/linux/privileged/reconcile_firewall.py %i"
        in unit
    )
    assert (
        "ReadWritePaths=/etc/ufw "
        "@DSM_ROOT@/runtime/hybrid-agent-state/privileged-firewall"
        in unit
    )


def test_hybrid_provisioning_uses_hybrid_firewall_unit():
    client = (
        ROOT / "dashboard" / "hybrid_instance_provisioning_client.py"
    ).read_text(encoding="utf-8")

    assert (
        '"CAPIVARA_FIREWALL_UNIT_TEMPLATE": '
        '"dsm-hybrid-agent-firewall@{instance_id}.service"'
        in client
    )
