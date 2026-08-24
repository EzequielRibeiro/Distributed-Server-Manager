#!/usr/bin/env python3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


def test_agents_v3_restores_remote_update_panel():
    html = (WEB / "agents.html").read_text(encoding="utf-8")
    for element_id in (
        "agent-update-panel",
        "agent-update-selector",
        "agent-installed-version",
        "agent-available-version",
        "agent-update-status",
        "agent-update-status-card",
        "agent-update-progress",
        "agent-update-progress-bar",
        "agent-update-error-details",
        "agent-update-error-detail-content",
        "agent-update-channel-form",
        "agent-rollout-form",
        "agent-rollout-agents",
        "agent-rollout-version",
        "agent-rollout-batch-size",
        "agent-rollout-channel",
        "agent-rollout-submit",
    ):
        assert f'id="{element_id}"' in html
    assert 'src="agent-updates-v3.js?v=3"' in html
    assert 'href="agent-updates-v3.css?v=3"' in html


def test_agents_v3_update_client_uses_existing_rollout_api():
    script = (WEB / "agent-updates-v3.js").read_text(encoding="utf-8")
    html = (WEB / "agents.html").read_text(encoding="utf-8")
    assert 'request("/agents")' in script
    assert "/agents/updates/status?agent_id=" in script
    assert 'request("/agents/updates/channel"' in script
    assert 'request("/agents/updates/rollouts"' in script
    assert "agent_ids: agentIds" in script
    assert "desired_version:" in script
    assert "batch_size:" in script
    assert "setTimeout(loadStatus" in script
    assert "agent-rollout-submit" in script
    assert "aria-valuenow" in script
    assert 'data-state' in script
    assert "Ver detalhes do erro" in html
    assert "last_error" in script
    assert "rollout_id" in script


def test_agents_v3_update_assets_are_registered_outside_legacy_server():
    composition = (ROOT / "dashboard" / "server_part14.py").read_text(encoding="utf-8")
    assert '"/agent-updates-v3.css"' in composition
    assert '"/agent-updates-v3.js"' in composition
