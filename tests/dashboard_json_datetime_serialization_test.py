#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

from json_serialization import normalize_json_value
import server_part17


def test_normalize_json_value_handles_nested_dates():
    timestamp = datetime(2026, 8, 23, 16, 10, 53, tzinfo=timezone.utc)
    payload = {
        "created_at": timestamp,
        "items": [{"day": date(2026, 8, 23)}],
        "tuple": (timestamp,),
    }

    normalized = normalize_json_value(payload)

    assert normalized["created_at"] == timestamp.isoformat()
    assert normalized["items"][0]["day"] == "2026-08-23"
    assert normalized["tuple"] == [timestamp.isoformat()]


def test_server_part17_send_json_normalizes_before_legacy_serializer(monkeypatch):
    captured = {}

    def fake_previous_send_json(self, code, payload):
        captured["code"] = code
        captured["payload"] = payload

    monkeypatch.setattr(server_part17, "_previous_send_json", fake_previous_send_json)
    timestamp = datetime(2026, 8, 23, 16, 10, 53)

    server_part17.json_safe_send_json(object(), 200, {"last_seen": timestamp})

    assert captured == {
        "code": 200,
        "payload": {"last_seen": "2026-08-23T16:10:53"},
    }
