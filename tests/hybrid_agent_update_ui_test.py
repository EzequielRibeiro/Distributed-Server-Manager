#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


def test_hybrid_agent_update_ui_is_controller_managed():
    script = (WEB / "agent-updates-v3.js").read_text(encoding="utf-8")
    html = (WEB / "agents.html").read_text(encoding="utf-8")

    assert "let controllerManaged = false;" in script
    assert 'status.rollout_supported === false' in script
    assert 'status.update_management === "controller"' in script
    assert "Gerenciado pelo Controller" in script
    assert "atualizado junto com o Controller" in script
    assert 'agent-updates-v3.js?v=6' in html
