#!/usr/bin/env python3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from log_viewer_metadata import decode_agent_metadata


def test_decodes_native_json_mapping_from_network_database_driver():
    raw = {"recent_logs": ["heartbeat ok", "update applied"], "telemetry": {"cpu": 1}}
    assert decode_agent_metadata(raw) == raw


def test_decodes_sqlite_json_text_and_binary_values():
    expected = {"recent_logs": ["heartbeat ok"]}
    assert decode_agent_metadata('{"recent_logs":["heartbeat ok"]}') == expected
    assert decode_agent_metadata(b'{"recent_logs":["heartbeat ok"]}') == expected


def test_malformed_or_non_object_metadata_degrades_to_empty_object():
    assert decode_agent_metadata("{'recent_logs': ['legacy-invalid-json']}") == {}
    assert decode_agent_metadata("[]") == {}
    assert decode_agent_metadata(None) == {}


def test_server_uses_shared_safe_metadata_decoder():
    source = (DASHBOARD / "server.py").read_text(encoding="utf-8")
    assert "from log_viewer_metadata import decode_agent_metadata" in source
    assert 'metadata = decode_agent_metadata(row["metadata_json"] if row else None)' in source
