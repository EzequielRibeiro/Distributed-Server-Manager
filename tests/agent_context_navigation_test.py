#!/usr/bin/env python3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


def test_agent_details_links_every_operation_to_the_selected_agent():
    html = (WEB / "agent-details.html").read_text(encoding="utf-8")
    script = (WEB / "agent-details.js").read_text(encoding="utf-8")
    for view in ("monitoring", "events", "diagnostics", "updates", "logs"):
        assert f'data-agent-view="{view}"' in html
    assert "agent-observability.html?agent_id=" in script
    assert "encodeURIComponent(agentId)" in script


def test_agent_context_page_has_no_agent_search_and_exposes_five_scoped_views():
    html = (WEB / "agent-observability.html").read_text(encoding="utf-8")
    assert 'href="dashboard-home-v3.css"' in html
    assert 'href="dashboard-v3.css"' not in html
    assert 'id="agent-context-nav"' in html
    assert 'id="agent-view-content"' in html
    assert "Agent / Node" not in html
    assert "placeholder=\"agent-id\"" not in html
    for view in ("monitoring", "events", "diagnostics", "updates", "logs"):
        assert f'data-view="{view}"' in html


def test_agent_context_client_filters_every_api_by_url_agent_id():
    script = (WEB / "agent-observability.js").read_text(encoding="utf-8")
    assert 'params.get("agent_id")' in script
    assert "/api/observability?mode=latest&agent_id=" in script
    assert "/api/events?agent_id=" in script
    assert "/api/agents/updates/status?agent_id=" in script
    assert 'source: "agent", server: agentId' in script
    assert "/api/log-viewer?" in script
    assert "setTimeout(refresh" in script


def test_agent_context_assets_are_registered_in_composition_layer():
    composition = (ROOT / "dashboard" / "server_part14.py").read_text(encoding="utf-8")
    for asset in ("/agent-observability.html", "/agent-observability.css", "/agent-observability.js"):
        assert f'"{asset}"' in composition
